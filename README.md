add some new features.
```bash
git clone https://github.com/maaamahAhh/updog-plus.git
cd updog
pip install poetry
poetry install
poetry run updog -d "/path/to/your/folder" -p 8080 --password yourpassword

# Linux Example
poetry run updog -d "/home/user/myfiles" -p 8080 --password 123

# Windows Example
poetry run updog -d "D:\myfiles" -p 8080 --password 123
```