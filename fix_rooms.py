#!/usr/bin/env python3
import re

with open('handlers/rooms.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Исправляем строки 209-226
for i in range(208, min(227, len(lines))):
    line = lines[i]
    if i == 209:  # if not is_anon:
        lines[i] = '            if not is_anon:\n'
    elif i == 210:  # display_name = author_name
        lines[i] = '                display_name = author_name\n'
    elif i == 211:  # if not author_name...
        lines[i] = '                if not author_name or author_name.strip() == "" or author_name.strip() == "ㅤ":\n'
    elif i == 220:  # else: (внутренний)
        lines[i] = '                else:\n'
    elif i == 225:  # else: (внешний для is_anon)
        lines[i] = '            else:\n'

with open('handlers/rooms.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("✅ Исправлено")
