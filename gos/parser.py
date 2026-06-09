import requests
import os

# Пример функции для скачивания файла техспецификации
def download_tech_spec(file_url, save_path):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(file_url, headers=headers)

    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return save_path
    else:
        print(f"Ошибка скачивания: {response.status_code}")
        return None

# В рамках MVP ты можешь вручную найти 5-10 ссылок на PDF/Word файлы
# тендеров с zakup.gov.kz и скормить их этой функции для теста.
