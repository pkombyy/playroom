#!/bin/bash
# Скрипт установки x-ui панели
# Автоматическая установка и настройка x-ui для обхода российских белых списков

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Установка x-ui панели${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# Проверка прав root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ Скрипт должен быть запущен с правами root (sudo)${NC}"
    exit 1
fi

# Проверка ОС
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VER=$VERSION_ID
else
    echo -e "${RED}❌ Не удалось определить ОС${NC}"
    exit 1
fi

echo -e "${GREEN}✅ ОС: $OS $VER${NC}"

# Обновление системы
echo -e "${YELLOW}📦 Обновление системы...${NC}"
if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    apt-get update -qq
    apt-get install -y curl wget socat > /dev/null 2>&1
elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ]; then
    yum update -y -q
    yum install -y curl wget socat > /dev/null 2>&1
else
    echo -e "${YELLOW}⚠️  Неподдерживаемая ОС, попытка установки...${NC}"
fi

# Проверка существующей установки
if command -v x-ui &> /dev/null; then
    echo -e "${YELLOW}⚠️  x-ui уже установлен${NC}"
    read -p "Переустановить? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}🗑️  Удаление старой установки...${NC}"
        x-ui uninstall || true
    else
        echo -e "${GREEN}✅ Используется существующая установка${NC}"
        exit 0
    fi
fi

# Установка x-ui через официальный скрипт
echo -e "${YELLOW}📥 Установка x-ui...${NC}"
bash <(curl -Ls https://raw.githubusercontent.com/vaxilu/x-ui/master/install.sh)

# Проверка установки
if ! command -v x-ui &> /dev/null; then
    echo -e "${RED}❌ Ошибка установки x-ui${NC}"
    exit 1
fi

echo -e "${GREEN}✅ x-ui успешно установлен${NC}"

# Запуск x-ui
echo -e "${YELLOW}🚀 Запуск x-ui...${NC}"
x-ui start

# Включение автозапуска
echo -e "${YELLOW}⚙️  Включение автозапуска...${NC}"
x-ui enable

# Проверка статуса
sleep 2
echo ""
echo -e "${YELLOW}📊 Статус x-ui:${NC}"
x-ui status

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Установка завершена!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}📋 Следующие шаги:${NC}"
echo ""
echo -e "${YELLOW}1. Войдите в веб-панель:${NC}"
echo -e "   ${BLUE}http://$(hostname -I | awk '{print $1}'):54321${NC}"
echo -e "   или"
echo -e "   ${BLUE}http://localhost:54321${NC}"
echo ""
echo -e "${YELLOW}2. Логин по умолчанию:${NC}"
echo -e "   ${BLUE}Username: admin${NC}"
echo -e "   ${BLUE}Password: admin${NC}"
echo -e "   ${RED}⚠️  Смените пароль после первого входа!${NC}"
echo ""
echo -e "${YELLOW}3. Настройте обход белых списков:${NC}"
echo -e "   ${BLUE}sudo /var/playroom/setup_xui_whitelist_bypass.sh${NC}"
echo ""
echo -e "${GREEN}✅ Готово!${NC}"
