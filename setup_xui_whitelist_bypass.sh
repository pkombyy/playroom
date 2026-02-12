#!/bin/bash
# Скрипт настройки x-ui для обхода российских белых списков
# Автоматически настраивает routing rules и DNS для обхода блокировок

set -e

echo "🔧 Настройка x-ui для обхода белых списков..."

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Проверка прав root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ Скрипт должен быть запущен с правами root (sudo)${NC}"
    exit 1
fi

# Проверка установки x-ui
if ! command -v x-ui &> /dev/null; then
    echo -e "${RED}❌ x-ui не установлен. Установите его сначала.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ x-ui найден${NC}"

# Путь к конфигурации x-ui
XUI_CONFIG_DIR="/usr/local/x-ui"
XUI_DB="${XUI_CONFIG_DIR}/x-ui.db"

# Проверка существования базы данных
if [ ! -f "$XUI_DB" ]; then
    echo -e "${YELLOW}⚠️  База данных x-ui не найдена. Запустите x-ui хотя бы раз для инициализации.${NC}"
    echo -e "${YELLOW}   Выполните: x-ui${NC}"
    exit 1
fi

# Функция для создания конфигурации routing rules
create_routing_config() {
    cat > /tmp/xui_routing_config.json << 'EOF'
{
  "domainStrategy": "IPIfNonMatch",
  "domainMatcher": "hybrid",
  "rules": [
    {
      "type": "field",
      "domain": [
        "geosite:ru"
      ],
      "outboundTag": "direct"
    },
    {
      "type": "field",
      "ip": [
        "geoip:ru",
        "geoip:private"
      ],
      "outboundTag": "direct"
    },
    {
      "type": "field",
      "domain": [
        "geosite:category-ads-all"
      ],
      "outboundTag": "block"
    },
    {
      "type": "field",
      "protocol": [
        "bittorrent"
      ],
      "outboundTag": "block"
    },
    {
      "type": "field",
      "domain": [
        "geosite:white-list"
      ],
      "outboundTag": "proxy"
    },
    {
      "type": "field",
      "domain": [
        "geosite:category-porn",
        "geosite:category-piracy"
      ],
      "outboundTag": "block"
    },
    {
      "type": "field",
      "domain": [
        "geosite:geolocation-!ru"
      ],
      "outboundTag": "proxy"
    },
    {
      "type": "field",
      "ip": [
        "geoip:!ru"
      ],
      "outboundTag": "proxy"
    },
    {
      "type": "field",
      "network": "tcp,udp",
      "outboundTag": "proxy"
    }
  ],
  "balancers": []
}
EOF
    echo -e "${GREEN}✅ Конфигурация routing rules создана${NC}"
}

# Функция для создания DNS конфигурации
create_dns_config() {
    cat > /tmp/xui_dns_config.json << 'EOF'
{
  "servers": [
    {
      "address": "77.88.8.8",
      "domains": [
        "geosite:ru"
      ],
      "expectIPs": [
        "geoip:ru"
      ],
      "skipFallback": false
    },
    {
      "address": "77.88.8.1",
      "domains": [
        "geosite:ru"
      ],
      "expectIPs": [
        "geoip:ru"
      ],
      "skipFallback": false
    },
    {
      "address": "https://1.1.1.1/dns-query",
      "domains": [
        "geosite:geolocation-!ru"
      ],
      "expectIPs": [
        "geoip:!ru"
      ],
      "skipFallback": false
    },
    {
      "address": "https://8.8.8.8/dns-query",
      "domains": [
        "geosite:geolocation-!ru"
      ],
      "skipFallback": false
    },
    {
      "address": "tls://1.1.1.1",
      "domains": [
        "geosite:geolocation-!ru"
      ],
      "skipFallback": false
    },
    {
      "address": "tls://8.8.8.8",
      "domains": [
        "geosite:geolocation-!ru"
      ],
      "skipFallback": false
    },
    "localhost"
  ],
  "queryStrategy": "UseIPv4",
  "disableCache": false,
  "disableFallback": false,
  "tag": "dns"
}
EOF
    echo -e "${GREEN}✅ Конфигурация DNS создана${NC}"
}

# Функция для обновления geo файлов
update_geo_files() {
    echo -e "${YELLOW}📥 Обновление geo файлов...${NC}"
    x-ui update-all-geofiles
    echo -e "${GREEN}✅ Geo файлы обновлены${NC}"
}

# Функция для применения настроек через API (если доступен)
apply_settings_via_api() {
    echo -e "${YELLOW}📝 Применение настроек...${NC}"
    echo -e "${YELLOW}⚠️  Для применения настроек routing и DNS необходимо:${NC}"
    echo -e "${YELLOW}   1. Войти в веб-панель x-ui${NC}"
    echo -e "${YELLOW}   2. Перейти в Settings -> Routing${NC}"
    echo -e "${YELLOW}   3. Вставить содержимое из /tmp/xui_routing_config.json${NC}"
    echo -e "${YELLOW}   4. Перейти в Settings -> DNS${NC}"
    echo -e "${YELLOW}   5. Вставить содержимое из /tmp/xui_dns_config.json${NC}"
    echo ""
    echo -e "${GREEN}📋 Конфигурационные файлы сохранены в:${NC}"
    echo -e "   - Routing: /tmp/xui_routing_config.json"
    echo -e "   - DNS: /tmp/xui_dns_config.json"
}

# Функция для создания скрипта автоматической настройки через API
create_api_setup_script() {
    cat > /tmp/xui_api_setup.py << 'PYEOF'
#!/usr/bin/env python3
"""
Скрипт для автоматической настройки x-ui через API
Требует: pip install requests
"""
import json
import sys
import getpass

def load_config(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def apply_config_via_api(api_url, username, password, routing_config, dns_config):
    import requests
    
    # Логин
    session = requests.Session()
    login_data = {
        "username": username,
        "password": password
    }
    
    try:
        response = session.post(f"{api_url}/login", json=login_data)
        if response.status_code != 200:
            print(f"❌ Ошибка входа: {response.status_code}")
            return False
        
        # Применение routing
        response = session.post(f"{api_url}/xray/routing", json=routing_config)
        if response.status_code == 200:
            print("✅ Routing настройки применены")
        else:
            print(f"⚠️  Ошибка применения routing: {response.status_code}")
        
        # Применение DNS
        response = session.post(f"{api_url}/xray/dns", json=dns_config)
        if response.status_code == 200:
            print("✅ DNS настройки применены")
        else:
            print(f"⚠️  Ошибка применения DNS: {response.status_code}")
        
        # Перезапуск xray
        response = session.post(f"{api_url}/xray/restart")
        if response.status_code == 200:
            print("✅ Xray перезапущен")
        else:
            print(f"⚠️  Ошибка перезапуска: {response.status_code}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 xui_api_setup.py <api_url> [username] [password]")
        print("Пример: python3 xui_api_setup.py http://localhost:54321")
        sys.exit(1)
    
    api_url = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) > 2 else input("Username: ")
    password = sys.argv[3] if len(sys.argv) > 3 else getpass.getpass("Password: ")
    
    routing_config = load_config("/tmp/xui_routing_config.json")
    dns_config = load_config("/tmp/xui_dns_config.json")
    
    if apply_config_via_api(api_url, username, password, routing_config, dns_config):
        print("✅ Настройка завершена успешно")
    else:
        print("❌ Ошибка настройки")
        sys.exit(1)
PYEOF
    chmod +x /tmp/xui_api_setup.py
    echo -e "${GREEN}✅ Скрипт для API настройки создан: /tmp/xui_api_setup.py${NC}"
}

# Основной процесс
main() {
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Настройка x-ui для обхода российских белых списков${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo ""
    
    # Обновление geo файлов
    read -p "Обновить geo файлы? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        update_geo_files
    fi
    
    # Создание конфигураций
    create_routing_config
    create_dns_config
    create_api_setup_script
    
    # Вывод инструкций
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Инструкции по применению настроек${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo ""
    apply_settings_via_api
    
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Дополнительные рекомендации${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}1. Используйте протоколы VLESS или VMESS с TLS${NC}"
    echo -e "${YELLOW}2. Включите WebSocket или gRPC для лучшей маскировки${NC}"
    echo -e "${YELLOW}3. Используйте домены вместо IP для серверов${NC}"
    echo -e "${YELLOW}4. Настройте fallback для обхода блокировок${NC}"
    echo -e "${YELLOW}5. Регулярно обновляйте geo файлы: x-ui update-all-geofiles${NC}"
    echo ""
    
    # Проверка статуса x-ui
    echo -e "${YELLOW}Проверка статуса x-ui...${NC}"
    x-ui status || echo -e "${YELLOW}⚠️  x-ui не запущен. Запустите: x-ui start${NC}"
    
    echo ""
    echo -e "${GREEN}✅ Настройка завершена!${NC}"
}

# Запуск
main
