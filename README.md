# 📥 YT-DL Web UI

[![Made with ❤️](https://img.shields.io/badge/Made%20with-%F0%9F%96%A4-red.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-active-success.svg)](#)

✨ Удобный и современный веб-интерфейс для скачивания **видео и аудио с YouTube**.  
Красивый UI, поддержка разных форматов и простота использования.  

---

## 📸 Скриншоты

![Главный экран](screens/main.png)
![Загруженное видео](screens/video.png)

---

## 🚀 Возможности

- 🎬 Скачивание видео в любом доступном качестве (360p, 720p, 1080p, 4K+)
- 🎵 Отдельное скачивание аудиодорожек (MP3 / M4A / Opus)
- 🖼 Минималистичный и адаптивный интерфейс
- 🛡 Полностью локальная работа — никакие данные не уходят наружу
- ⚡ Быстрая обработка с помощью `yt-dlp`

---

## ⚡ Установка


### 1. Клонируй репозиторий
```bash
git clone https://github.com/Kevanko/YTD.git
cd YTD


### 2. Установи зависимости

**Python 3**  
Убедись, что Python установлен. На разных системах это делается так:  
- Debian/Ubuntu: `sudo apt install python3-pip`  
- Fedora: `sudo dnf install python3-pip`  
- macOS (Homebrew): `brew install python`  

Проверить версию Python: `python --version`

**yt-dlp**  
Установи основной инструмент для скачивания:  
`pip install -U yt-dlp`  
Проверить версию: `yt-dlp --version`

**ffmpeg**  
Установи ffmpeg для обработки аудио и видео:  
- Debian/Ubuntu: `sudo apt install ffmpeg`  
- Fedora: `sudo dnf install ffmpeg`  
- macOS: `brew install ffmpeg`

### 3. Запуск
Для запуска программы используй:  
`python3 add.py`

Программа будет доступна по адресу:  
[http://127.0.0.1:5000/](http://127.0.0.1:5000/)  
или  
[http://localhost:5000](http://localhost:5000)

---
