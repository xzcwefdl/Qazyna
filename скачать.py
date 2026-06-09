import os
import re
from bs4 import BeautifulSoup

# Укажите папку, куда вы скачали все 100 HTML-страниц материалов
SOURCE_HTML_DIR = 'bunkr_originals'
# Результат
OUTPUT_LINKS_FILE = 'all_direct_links.txt'

direct_links = set()

print("Анализ локальных страниц...")
for file_name in os.listdir(SOURCE_HTML_DIR):
    if file_name.endswith('.html'):
        file_path = os.path.join(SOURCE_HTML_DIR, file_name)

        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

            # Парсим конкретную страницу материала (как hngnirfinrr.html)
            # Ищем ссылки в тегах source, video, img или кнопках скачивания
            for tag in soup.find_all(['source', 'video', 'img', 'a']):
                src = tag.get('src') or tag.get('href') or tag.get('data-src')
                if src and any(ext in src.lower() for ext in ['.mp4', '.mov', '.jpg', '.jpeg', '.png']):
                    # Исключаем элементы дизайна сайта
                    if 'logo' not in src.lower() and 'fav' not in src.lower():
                        direct_links.add(src)

# Сохраняем чистые ссылки в файл
with open(OUTPUT_LINKS_FILE, 'w', encoding='utf-8') as f:
    for link in sorted(direct_links):
        f.write(link + '\n')

print(f"Готово! Из локальных файлов извлечено {len(direct_links)} прямых ссылок на оригиналы.")
print(f"Список сохранен в файл: {OUTPUT_LINKS_FILE}")
print("Теперь этот текстовый файл можно импортировать в любой менеджер закачек (Download Master / JDownloader) для мгновенного скачивания.")
