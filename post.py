import os
import sys
import time
import base64
import requests
import anthropic
from pathlib import Path

# GitHub Actions ortam değişkenlerinden alınan bilgiler
IG_USER_ID = os.environ["IG_USER_ID"]
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "CanZeray/zerayartinstagram")


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


def generate_caption(image_path):
    """Claude ile Türkçe + İngilizce kısa açıklama üret"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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


def post_to_instagram(image_url, caption):
    """Instagram Graph API üzerinden görseli paylaş"""
    base_url = "https://graph.facebook.com/v20.0"

    # Adım 1: Medya konteyneri oluştur
    print("Medya konteyneri oluşturuluyor...")
    response = requests.post(
        f"{base_url}/{IG_USER_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": PAGE_ACCESS_TOKEN,
        },
    )
    result = response.json()

    if "error" in result:
        print(f"Hata (container): {result['error']}")
        sys.exit(1)

    creation_id = result["id"]
    print(f"Konteyner oluşturuldu: {creation_id}")

    # Adım 2: Yayınla
    print("Paylaşım yapılıyor...")
    time.sleep(5)

    response = requests.post(
        f"{base_url}/{IG_USER_ID}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": PAGE_ACCESS_TOKEN,
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

    image_path = get_next_image()
    print(f"Seçilen görsel: {image_path.name}")

    print("Claude ile açıklama üretiliyor...")
    caption = generate_caption(image_path)
    print(f"Açıklama:\n{caption}\n")

    image_url = get_image_url(image_path)
    print(f"Görsel URL: {image_url}")

    post_to_instagram(image_url, caption)
    move_to_posted(image_path)

    print("=== Tamamlandı ===")


if __name__ == "__main__":
    main()
