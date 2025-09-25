# 📥 YT-DL Web UI

[![Made with ❤️](https://img.shields.io/badge/Made%20with-%F0%9F%96%A4-red.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-active-success.svg)](#)

✨ Удобный и современный веб-интерфейс для скачивания **видео и аудио с YouTube**.  
Красивый UI, поддержка разных форматов и простота использования.  

---

![Главный экран](screens/main.png)
![Загруженно видео](screens/video.png)
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
- 1. Python 3
```bash
sudo apt install python3-pip   # (Debian/Ubuntu)
sudo dnf install python3-pip   # (Fedora)
brew install python            # (macOS + Homebrew)

python --version

- 2. yt-dlp (основной инструмент)
```bash
pip install -U yt-dlp
yt-dlp --version

- 3. ffmpeg
```bash
sudo apt install ffmpeg   # Debian/Ubuntu
sudo dnf install ffmpeg   # Fedora
brew install ffmpeg # (macOS)

### 3. Запусти
```bash
python3 add.py
- Программа будет доступна по адрессу: 
http://127.0.0.1:5000/ 
- Либо
localhost:5000