import requests
import json
import logging
import sys
from typing import List, Dict, Optional
from xml.etree import ElementTree

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

LOGIN = ""
PASSWORD_SHA1 = ""
IIKO_HOST = ""


def login(session: requests.Session) -> str:
    """
    Авторизуется, возвращает токен сессии.
    """
    auth_url = f"{IIKO_HOST}/resto/api/auth"
    payload = {"login": LOGIN, "pass": PASSWORD_SHA1}
    try:
        response = session.post(auth_url, data=payload, timeout=10)
        response.raise_for_status()
        token = response.text.strip()
        logging.info(f"Успешная авторизация. Получен токен: {token}")
        return token
    except requests.exceptions.RequestException as exc:
        logging.error(f"Ошибка при авторизации: {exc}")
        sys.exit(1)


def logout(session: requests.Session, token: str):
    """
    Завершает сессию (logout).
    """
    logout_url = f"{IIKO_HOST}/resto/api/logout"
    payload = {"key": token}
    try:
        response = session.post(logout_url, data=payload, timeout=10)
        if response.status_code == 200:
            logging.info("Успешный logout. Лицензия освобождена.")
        else:
            logging.warning(f"Logout вернул статус {response.status_code}.")
    except requests.exceptions.RequestException as exc:
        logging.warning(f"Ошибка при logout: {exc}")


def fetch_all_suppliers(session: requests.Session, token: str) -> List[Dict]:
    """
    Возвращает список всех поставщиков из iiko.

    Для iiko 3.9 по умолчанию /resto/api/suppliers может вернуть XML.
    Если .json() вызывает ошибку, нужно парсить XML вручную.
    """
    url = f"{IIKO_HOST}/resto/api/suppliers"
    params = {
        "key": token,
        # В документации 3.9 также есть параметр revisionFrom. Иногда нужно = -1:
        # "revisionFrom": "-1"
    }
    try:
        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()

        # Попробуем сначала считать как JSON:
        try:
            suppliers = response.json()
            # Если успешно, значит сервер вернул JSON. Возвращаем.
            return suppliers if isinstance(suppliers, list) else []
        except ValueError:
            # Если возникает ошибка "Expecting value: line 1 column 1 (char 0)",
            # значит ответ, скорее всего, в XML.
            logging.warning("Похоже, /suppliers вернуло XML. Считываем как XML.")

            text_data = response.text
            # При желании можем вывести сырой ответ для отладки:
            # print("RAW suppliers response:\n", text_data)

            # Парсим XML
            # Пример структуры: <employees> <employee> ... </employee> </employees>
            # В XSD сказано, что корневой элемент может быть "employee" или "employees".

            root = ElementTree.fromstring(text_data)
            # Предположим, что root.tag == "employees" (или "employee").
            # Соберём все теги <employee> и извлечём нужные поля.
            # В iiko 3.9 каждый <employee> описывает поставщика, если employee/supplier="true".

            suppliers_list = []
            # Если корневой элемент = <employees>, пробежимся по всем <employee>.
            # Если root.tag == "employee", значит возможно только один поставщик, обернём в список.
            if root.tag == "employees":
                employees = root.findall("employee")
            elif root.tag == "employee":
                # Единственный поставщик
                employees = [root]
            else:
                logging.error(f"Неизвестный корневой тег: {root.tag}")
                return suppliers_list

            for emp in employees:
                emp_data = {}
                for child in emp:
                    emp_data[child.tag] = child.text or ""
                suppliers_list.append(emp_data)

            return suppliers_list

    except requests.exceptions.RequestException as exc:
        logging.error(f"Ошибка при получении списка поставщиков: {exc}")
        return []


def fetch_supplier_id(suppliers: List[Dict], supplier_name: str) -> Optional[str]:
    """
    Поиск в уже загруженном списке поставщиков (словари).
    Ищем по точному совпадению поля "name".
    Возвращаем ID, если нашли.
    """
    for sup in suppliers:
        # sup.get("name") - строка названия (например, "Лубчук Л.В. ФОП")
        if sup.get("name", "").strip().lower() == supplier_name.lower():
            return sup.get("id")
    return None


def pretty_print_suppliers(suppliers: List[Dict]):
    """
    Выводит список поставщиков в консоли (id, code, name, supplier, deleted...)
    Для XML-тэгов может быть больше полей, например <login>, <phone>, <supplier>="true"
    """
    if not suppliers:
        print("Список поставщиков пуст!")
        return

    # Чтобы узнать, какие поля есть у поставщика, выведите suppliers[0] целиком:
    # print("DEBUG supplier keys:", suppliers[0].keys())
    # Возможно, поля: id, code, name, supplier, deleted, phone, ...

    columns = ["id", "code", "name", "supplier", "deleted"]

    # Заголовки
    headers = [col.upper() for col in columns]

    # Формируем строки
    rows = []
    for s in suppliers:
        row = [str(s.get(col, "")) for col in columns]
        rows.append(row)

    # Считаем ширину колонок
    col_widths = [
        max(len(row[i]) for row in rows + [headers]) for i in range(len(columns))
    ]

    # Разделитель
    separator = "+".join("-" * (w + 2) for w in col_widths)
    separator = f"+{separator}+"

    # Строка заголовка
    header_row = "|".join(
        f" {headers[i].ljust(col_widths[i])} " for i in range(len(headers))
    )
    header_row = f"|{header_row}|"

    print(separator)
    print(header_row)
    print(separator)
    for row in rows:
        row_str = "|".join(
            f" {row[i].ljust(col_widths[i])} " for i in range(len(row))
        )
        row_str = f"|{row_str}|"
        print(row_str)
    print(separator)


def main():
    with requests.Session() as session:
        token = login(session)
        try:
            # 1) Получаем всех поставщиков (список словарей)
            suppliers = fetch_all_suppliers(session, token)

            # 2) Печатаем их в консоль
            pretty_print_suppliers(suppliers)

            # 3) Ищем конкретного поставщика
            search_name = "Лубчук Л.В. ФОП"  # Пример
            found_id = fetch_supplier_id(suppliers, search_name)
            if found_id:
                logging.info(f"Найден поставщик '{search_name}', ID: {found_id}")
            else:
                logging.warning(f"Поставщик '{search_name}' не найден.")
        finally:
            logout(session, token)


if __name__ == "__main__":
    main()
