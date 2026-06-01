import os
import sys
import time
import base64
import io
import requests
import anthropic
from pathlib import Path
from PIL import Image

# GitHub Secrets'tan alınan bilgiler
IG_USER_ID = os.environ["IG_USER_ID"]
LONG_LIVED_USER_TOKEN = os.environ["LONG_LIVED_USER_TOKEN"]
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")  # yedek olarak
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
PAGE_ID = os.environ.get("PAGE_ID", "1097256760138045")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "CanZeray/zerayartinstagram")


def get_fresh_page_token():
    """Uzun ömürlü kullanıcı tokenından taze sayfa tokenı al"""
    response = requests.get(
        "https://graph.facebook.com/v20.0/me/accounts",
        params={"access_token": LONG_LIVED_USER_TOKEN}
    )
    data = response.json()

    if "error" in data:
        print(f"Kullanıcı token hatası: {data['error']}")
        print("Yedek PAGE_ACCESS_TOKEN kullanılıyor...")
        return PAGE_ACCESS_TOKEN

    for page in data.get("data", []):
        if page["id"] == PAGE_ID:
            print(f"Taze sayfa tokenı alındı ✓")
            return page["access_token"]

    print("ZerayArt sayfası bulunamadı, yedek token kullanılıyor...")
    return PAGE_ACCESS_TOKEN


def get_next_image():
    """images/ klasöründeki ilk görseli seç"""
    images_dir = Path("images")
    if not images_dir.exists():
        print("images/ klasörü bulunamadı!")
        sys.exit(0)

    image_files = sorted([
        f for f in images_dir.iterdir()
        if f.suffix.lower() in [".jpg", ".jpeg", ".png"]
    ])

    if not image_files:
        print("Paylaşılacak görsel kalmadı!")
        sys.exit(0)

    return image_files[0]


def compress_image_for_api(image_path, max_bytes=4.5 * 1024 * 1024):
    """Görseli Anthropic API limitinin altına sıkıştır (max 4.5 MB)"""
    with Image.open(image_path) as img:
        # RGBA veya P modunu RGB'ye çevir
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Önce kaliteyi düşürerek dene
        quality = 90
        while quality >= 10:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            size = buffer.tell()
            print(f"  Sıkıştırma deneniyor (quality={quality}): {size / 1024 / 1024:.2f} MB")
            if size <= max_bytes:
                buffer.seek(0)
                return buffer.read(), "image/jpeg"
            quality -= 10

        # Hala büyükse boyutu yarıya indir
        print("  Boyut küçültülüyor (yarıya)...")
        img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        return buffer.read(), "image/jpeg"


def generate_caption(image_path):
    """Claude ile Türkçe + İngilizce kısa açıklama üret"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"  Görsel boyutu kontrol ediliyor...")
    file_size = image_path.stat().st_size
    print(f"  Orijinal boyut: {file_size / 1024 / 1024:.2f} MB")

    if file_size > 4.5 * 1024 * 1024:
        print(f"  Görsel 4.5 MB üzerinde, sıkıştırılıyor...")
        image_data_bytes, media_type = compress_image_for_api(image_path)
        image_data = base64.standard_b64encode(image_data_bytes).decode("utf-8")
        print(f"  Sıkıştırma tamamlandı ✓")
    else:
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        suffix = image_path.suffix.lower()
        media_type = "image/jpeg" if suffix in [".jpg", ".jpeg"] else "image/png"

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Bu resim sanatçısının Instagram gönderisi için kısa ve sade bir açıklama yaz.\n\n"
                            "Sadece şu formatı kullan, başka hiçbir şey ekleme:\n\n"
                            "[Türkçe açıklama — 1-2 cümle]\n\n"
                            "[English caption — 1-2 sentences]\n\n"
                            "#sanat #ressam #tablo #painting #art #oilpainting #zerayart"
                        ),
                    },
                ],
            }
        ],
    )

    return message.content[0].text.strip()


def get_image_url(image_path):
    """Görselin GitHub raw URL'ini oluştur"""
    filename = image_path.name
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/images/{filename}"


def post_to_instagram(image_url, caption, page_token):
    """Instagram Graph API üzerinden görseli paylaş"""
    base_url = "https://graph.facebook.com/v20.0"

    print("Medya konteyneri oluşturuluyor...")
    response = requests.post(
        f"{base_url}/{IG_USER_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": page_token,
        },
    )
    result = response.json()

    if "error" in result:
        print(f"Hata (container): {result['error']}")
        sys.exit(1)

    creation_id = result["id"]
    print(f"Konteyner oluşturuldu: {creation_id}")

    print("Paylaşım yapılıyor...")
    time.sleep(5)

    response = requests.post(
        f"{base_url}/{IG_USER_ID}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": page_token,
        },
    )
    result = response.json()

    if "error" in result:
        print(f"Hata (publish): {result['error']}")
        sys.exit(1)

    print(f"Başarıyla paylaşıldı! Post ID: {result['id']}")
    return result["id"]


def move_to_posted(image_path):
    """Paylaşılan görseli posted/ klasörüne taşı"""
    posted_dir = Path("posted")
    posted_dir.mkdir(exist_ok=True)
    dest = posted_dir / image_path.name
    image_path.rename(dest)
    print(f"{image_path.name} → posted/ klasörüne taşındı.")


def main():
    print("=== ZerayArt Instagram Otomasyon Başladı ===")

    # Her çalıştırmada taze token al
    page_token = get_fresh_page_token()

    image_path = get_next_image()
    print(f"Seçilen görsel: {image_path.name}")

    print("Claude ile açıklama üretiliyor...")
    caption = generate_caption(image_path)
    print(f"Açıklama:\n{caption}\n")

    image_url = get_image_url(image_path)
    print(f"Görsel URL: {image_url}")

    post_to_instagram(image_url, caption, page_token)
    move_to_posted(image_path)

    print("=== Tamamlandı ===")


if __name__ == "__main__":
    main()
