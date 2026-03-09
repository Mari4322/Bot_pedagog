## Teacher bot (aiogram + SQLite)

### Важно про Python на Windows
Сейчас у вас установлен Python **3.14**, а многие библиотеки (включая `aiogram`/`pydantic`) ещё **не имеют готовых колёс** под 3.14 и пытаются собираться из исходников (нужны Rust/C++ build-tools).

Чтобы проект ставился “в один клик”, установите **Python 3.12 (64-bit)** с сайта python.org и поставьте галочку **“Add python.exe to PATH”**.

После установки проверьте:

```bash
py -0p
py -3.12 --version
```

### Установка и запуск
Из корня проекта:

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r teacher_bot\requirements.txt
```

Заполните `teacher_bot/.env`, затем запустите:

```bash
.venv\Scripts\python teacher_bot\bot.py
```

