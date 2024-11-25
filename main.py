import asyncio
import json
import os
import threading
from datetime import datetime, timedelta

import schedule
import time
from playwright.async_api import async_playwright
from decimal import Decimal
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import shutil



logging.basicConfig(
    level=logging.INFO,  # Уровень логирования
    format='%(asctime)s - %(levelname)s - %(message)s',  # Формат сообщения
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("program.log"),  # Логировать в файл
        logging.StreamHandler()  # Логировать в консоль
    ]
)
import sys

CONFIG_FILE = "config.json"




#CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Функция для загрузки конфигурации
def load_config(config_file=CONFIG_FILE):
    try:
        with open(config_file, "r") as file:
            config = json.load(file)
        return config
    except FileNotFoundError:
        raise Exception(f"Конфигурационный файл {config_file} не найден.")
    except json.JSONDecodeError:
        raise Exception(f"Ошибка при разборе конфигурационного файла {config_file}.")

# Загрузка конфигурации
try:
    config = load_config()
except Exception as e:
    logging.error(f"Ошибка при загрузке конфигурации: {e}, проверьте конфигурационный файл и перезапустите приложение")
    exit(1)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'credentials.json'

spreadsheet_id = config["sheet_id"]  # замените на ID вашей таблицы


def authenticate_google_sheets():
    """Аутентификация в Google Sheets API."""
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials)

def check_header(sheet, spreadsheet_id, header, sheet_name="Sheet1"):
    """
    Проверяет, соответствует ли заголовок таблицы заданному header.
    Если нет, устанавливает его.
    """
    try:
        # Получаем первую строку таблицы
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A1:Z1').execute()
        values = result.get('values', [])

        # Проверяем, соответствует ли заголовок
        if not values or values[0] != header[0]:
            sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A1',
                valueInputOption='RAW',
                body={'values': header}
            ).execute()
            logging.info("Установлен/обновлён header таблицы.")
    except HttpError as err:
        logging.warning(f"Ошибка при проверке заголовка таблицы")

def add_date_if_missing(sheet, spreadsheet_id, next_day=False, sheet_name="Sheet1"):
    """
    Проверяет наличие указанной даты (текущей или следующей) в первой колонке.
    Если дата отсутствует, добавляет её после последней записи в таблице.
    Возвращает номер строки для новой записи данных.
    """
    current_date = datetime.now() + timedelta(days=1) if next_day else datetime.now()
    current_date_str = current_date.strftime('%Y-%m-%d')

    try:
        # Получаем первую колонку
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A:A').execute()
        values = result.get('values', [])

        # Проверяем наличие текущей даты
        for i, row in enumerate(values):
            if row and row[0] == current_date_str:
                #print(f"Дата '{current_date_str}' уже существует в строке {i + 1}.")
                return i + 2  # Следующая строка после найденной даты

        # Если текущей даты нет, добавляем её после последней записи
        last_filled_row = find_last_filled_row(sheet, spreadsheet_id, sheet_name)
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A{last_filled_row}',
            valueInputOption='RAW',
            body={'values': [[current_date_str]]}
        ).execute()
        #print(f"Дата '{current_date_str}' добавлена в строку {last_filled_row}.")
        return last_filled_row + 1
    except HttpError as err:
        #print(f"Ошибка при проверке или добавлении даты: {err}")
        return None

def find_last_filled_row(sheet, spreadsheet_id, sheet_name="Sheet1", check_range=50):
    """
    Находит последнюю заполненную строку в таблице, пропуская пустые строки.
    Возвращает номер строки, следующей за последней заполненной.
    """
    try:
        # Получаем все строки таблицы
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A:Z').execute()
        values = result.get('values', [])

        # Проходим строки в обратном порядке
        for i in range(len(values) - 1, -1, -1):
            if any(cell.strip() for cell in values[i]):
                #print(f"Последняя заполненная строка: {i + 1}")
                return i + 2  # Следующая строка после последней заполненной

        # Если таблица полностью пустая
        #print("Таблица полностью пустая.")
        return 2  # После заголовка
    except HttpError as err:
        #print(f"Ошибка при поиске последней заполненной строки: {err}")
        return None

def write_data_to_row(sheet, spreadsheet_id, match_pairs, start_row, sheet_name="Sheet1"):
    """
    Записывает данные матчей в таблицу Google Sheets, начиная с указанной строки.

    Аргументы:
    - sheet: объект Google Sheets API.
    - spreadsheet_id: ID таблицы.
    - match_pairs: список матчей (в виде списка словарей).
    - start_row: строка, с которой начать запись.
    - sheet_name: имя листа в таблице.
    """
    try:
        # Преобразуем данные match_pairs в формат для записи
        data_to_write = [
            [
                match["K1"], match["K2"], str(match["odds"]),
                str(match["over"]), str(match["first_time"]),
                match["total_k1"], match["total_k2"]
            ]
            for match in match_pairs
        ]

        # Определяем диапазон для записи
        range_ = f'{sheet_name}!B{start_row}'

        # Записываем данные в таблицу
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption='RAW',
            body={'values': data_to_write}
        ).execute()
        logging.info(f"Данные успешно записаныв таблицу, начиная со строки {start_row}.")
    except HttpError as err:
        logging.warning(f"Ошибка при записи данных в таблицу")

def update_google_sheet(spreadsheet_id, match_pairs, next_day=False, sheet_name="Sheet1"):
    """
    Функция для последовательного выполнения:
    1. Проверка заголовка таблицы.
    2. Добавление текущей или следующей даты.
    3. Определение строки для записи.
    4. Запись данных.
    """
    logging.info("Начали записывать данные в таблицу")
    if not match_pairs or match_pairs is None or len(match_pairs) == 0:
        logging.warning("Список матчей пуст, обновление таблицы не требуется.")
        return

    service = authenticate_google_sheets()
    sheet = service.spreadsheets()

    header = [
        ["Дата/число", "Команда1", "Команда2", "КоефНаПеремогуФаворита",
         "КоефТоталБільше2.5", "КоефТоталБільше0.5 1Т",
         "ВартістьКоманди1", "ВартістьКоманди2"]
    ]

    # Шаг 1: Проверка заголовка
    check_header(sheet, spreadsheet_id, header, sheet_name)

    # Шаг 2: Добавление текущей или следующей даты
    start_row = add_date_if_missing(sheet, spreadsheet_id, next_day, sheet_name)

    # Шаг 3: Поиск строки для записи данных
    start_row = find_last_filled_row(sheet, spreadsheet_id, sheet_name)

    # Шаг 4: Запись данных
    write_data_to_row(sheet, spreadsheet_id, match_pairs, start_row, sheet_name)

# def update_matches_in_google_sheet(spreadsheet_id, match_pairs, sheet_name="Sheet1"):
#     """
#     Обновляет данные матчей в таблице Google Sheets:
#     - Удаляет строки матчей, которые отсутствуют во входящем списке `match_pairs`.
#     - Обновляет строки матчей, если они есть в таблице и во входящем списке.
#     - Добавляет новые строки для матчей, отсутствующих в таблице.
#
#     Аргументы:
#     - sheet: объект Google Sheets API.
#     - spreadsheet_id: ID таблицы.
#     - match_pairs: список матчей (в виде списка словарей).
#     - sheet_name: имя листа в таблице.
#     """
#     logging.info("starting update_matches_in_google_sheet method")
#     service = authenticate_google_sheets()
#     sheet = service.spreadsheets()
#
#     current_date_str = datetime.now().strftime('%Y-%m-%d')
#
#     try:
#         # Получение всех данных из таблицы
#         result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A:Z').execute()
#         values = result.get('values', [])
#
#         # Определяем строку с текущей датой
#         date_row = None
#         for i, row in enumerate(values):
#             if row and row[0] == current_date_str:
#                 date_row = i
#                 break
#
#         #print(date_row)
#         if date_row is None:
#             #print(f"Дата '{current_date_str}' не найдена в таблице.")
#             return
#
#         # Определяем последнюю заполненную строку
#         last_filled_row = len(values)
#         for i in range(len(values) - 1, -1, -1):
#             if any(cell.strip() for cell in values[i]):
#                 last_filled_row = i + 1
#                 break
#
#         #print(f"Дата находится в строке: {date_row}, последняя заполненная строка: {last_filled_row}.")
#
#         # Формируем словарь текущих матчей в таблице
#         current_matches = {}
#         for i in range(date_row + 1, last_filled_row + 1):
#             if i < len(values) and len(values[i]) > 2:
#                 key = (values[i][1], values[i][2])  # Ключ - кортеж (K1, K2)
#                 current_matches[key] = i+1  # Номер строки
#
#         # Формируем словарь новых матчей
#         new_matches = {(match["K1"], match["K2"]): match for match in match_pairs}
#
#         # Удаляем строки матчей, которых нет в новом списке
#         rows_to_delete = []
#         for key, row_index in current_matches.items():
#             if key not in new_matches:
#                 rows_to_delete.append(row_index)
#
#         if rows_to_delete:
#             rows_to_delete.sort(reverse=True)
#             for row_index in rows_to_delete:
#                 sheet.values().clear(
#                     spreadsheetId=spreadsheet_id,
#                     range=f'{sheet_name}!A{row_index}:Z{row_index}'
#                 ).execute()
#             logging.info(f"Удалены строки(больше неактуальные): {rows_to_delete}")
#
#         # Обновляем существующие матчи и добавляем новые
#         for match in match_pairs:
#             key = (match["K1"], match["K2"])
#             if key in current_matches:
#                 # Обновляем существующий матч
#                 row_index = current_matches[key]
#                 data = [[
#                     match["K1"], match["K2"], str(match["odds"]),
#                     str(match["over"]), str(match["first_time"]),
#                     match["total_k1"], match["total_k2"]
#                 ]]
#                 sheet.values().update(
#                     spreadsheetId=spreadsheet_id,
#                     range=f'{sheet_name}!B{row_index}',
#                     valueInputOption='RAW',
#                     body={'values': data}
#                 ).execute()
#                 #print(f"Обновлена строка {row_index} для матча: {key}")
#             else:
#                 # Добавляем новый матч
#                 last_filled_row += 1
#                 data = [[
#                     match["K1"], match["K2"], str(match["odds"]),
#                     str(match["over"]), str(match["first_time"]),
#                     match["total_k1"], match["total_k2"]
#                 ]]
#                 sheet.values().update(
#                     spreadsheetId=spreadsheet_id,
#                     range=f'{sheet_name}!B{last_filled_row}',
#                     valueInputOption='RAW',
#                     body={'values': data}
#                 ).execute()
#                 #print(f"Добавлен новый матч в строку {last_filled_row}: {key}")
#         logging.info("Данные успешно обновлены в таблице.")
#     except HttpError as err:
#         logging.warning(f"Ошибка при обновлении данных в таблице")

def update_matches_in_google_sheet(spreadsheet_id, match_pairs, sheet_name="Sheet1"):
    """
    Обновляет данные матчей в таблице Google Sheets:
    - Проверяет наличие заголовка таблицы, добавляет его при необходимости.
    - Добавляет текущую дату, если она отсутствует.
    - Удаляет строки матчей, которые отсутствуют во входящем списке `match_pairs`.
    - Обновляет строки матчей, если они есть в таблице и во входящем списке.
    - Добавляет новые строки для матчей, отсутствующих в таблице.

    Аргументы:
    - spreadsheet_id: ID таблицы.
    - match_pairs: список матчей (в виде списка словарей).
    - sheet_name: имя листа в таблице.
    """
    logging.info("Начали обнослять таблицу")
    if match_pairs is None or not match_pairs or len(match_pairs) == 0:
        logging.warning("Список матчей пуст, обновление таблицы не требуется.")
        return
    service = authenticate_google_sheets()
    sheet = service.spreadsheets()

    # Заголовок таблицы
    header = [
        ["Дата/число", "Команда1", "Команда2", "КоефНаПеремогуФаворита",
         "КоефТоталБільше2.5", "КоефТоталБільше0.5 1Т",
         "ВартістьКоманди1", "ВартістьКоманди2"]
    ]

    # Проверяем наличие заголовка
    check_header(sheet, spreadsheet_id, header, sheet_name)

    # Проверяем наличие текущей даты, добавляем, если отсутствует
    current_date_str = datetime.now().strftime('%Y-%m-%d')
    start_row = add_date_if_missing(sheet, spreadsheet_id, next_day=False, sheet_name=sheet_name)

    # Получаем все строки таблицы для дальнейших обновлений
    try:
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A:Z').execute()
        values = result.get('values', [])

        # Определяем строку с текущей датой
        date_row = None
        for i, row in enumerate(values):
            if row and row[0] == current_date_str:
                date_row = i
                break

        if date_row is None:
            logging.error(f"Дата '{current_date_str}' не найдена, хотя должна была быть добавлена.")
            return

        # Формируем словарь текущих матчей в таблице
        current_matches = {}
        last_filled_row = len(values)
        for i in range(date_row + 1, last_filled_row):
            if i < len(values) and len(values[i]) > 2:
                key = (values[i][1], values[i][2])  # Ключ - кортеж (K1, K2)
                current_matches[key] = i + 1  # Номер строки

        # Формируем словарь новых матчей
        new_matches = {(match["K1"], match["K2"]): match for match in match_pairs}

        # Удаляем строки матчей, которых нет в новом списке
        rows_to_delete = []
        for key, row_index in current_matches.items():
            if key not in new_matches:
                rows_to_delete.append(row_index)

        if rows_to_delete:
            rows_to_delete.sort(reverse=True)
            for row_index in rows_to_delete:
                sheet.values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=f'{sheet_name}!A{row_index}:Z{row_index}'
                ).execute()
            logging.info(f"Удалены строки (больше неактуальные): {rows_to_delete}")

        # Обновляем существующие матчи и добавляем новые
        for match in match_pairs:
            key = (match["K1"], match["K2"])
            if key in current_matches:
                # Обновляем существующий матч
                row_index = current_matches[key]
                data = [[
                    match["K1"], match["K2"], str(match["odds"]),
                    str(match["over"]), str(match["first_time"]),
                    match["total_k1"], match["total_k2"]
                ]]
                sheet.values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f'{sheet_name}!B{row_index}',
                    valueInputOption='RAW',
                    body={'values': data}
                ).execute()
                logging.info(f"Обновлена строка {row_index} для матча: {key}")
            else:
                # Добавляем новый матч
                last_filled_row += 1
                data = [[
                    match["K1"], match["K2"], str(match["odds"]),
                    str(match["over"]), str(match["first_time"]),
                    match["total_k1"], match["total_k2"]
                ]]
                sheet.values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f'{sheet_name}!B{last_filled_row}',
                    valueInputOption='RAW',
                    body={'values': data}
                ).execute()
                logging.info(f"Добавлен новый матч в строку {last_filled_row}: {key}")
        logging.info("Данные успешно обновлены в таблице.")
    except HttpError as err:
        logging.warning(f"Ошибка при обновлении данных в таблице: {err}")


def remove_empty_rows_below_date(sheet_name="Sheet1"):
    """
    Ищет строку с текущей датой в первой колонке и удаляет пустые строки ниже неё,
    переписывая данные.

    Аргументы:
    - spreadsheet_id: ID таблицы Google Sheets.
    - sheet_name: имя листа в таблице.
    """
    service = authenticate_google_sheets()
    sheet = service.spreadsheets()

    # Текущая дата
    current_date_str = datetime.now().strftime('%Y-%m-%d')

    try:
        # Получаем все строки из таблицы
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A:Z').execute()
        values = result.get('values', [])

        if not values:
            return

        # Определяем строку с текущей датой
        date_row_index = None
        for i, row in enumerate(values):
            if row and row[0] == current_date_str:  # Проверяем дату в первой колонке
                date_row_index = i
                break

        if date_row_index is None:
            #print(f"Дата '{current_date_str}' не найдена в таблице.")
            return

        #print(f"Дата '{current_date_str}' найдена в строке {date_row_index + 1}.")

        # Отбираем строки ниже строки с текущей датой
        rows_below_date = values[date_row_index + 1:]

        # Отфильтровываем только непустые строки
        non_empty_rows = [row for row in rows_below_date if any(cell.strip() for cell in row)]

        # Перезаписываем таблицу: очищаем строки ниже текущей даты и добавляем только непустые
        start_row = date_row_index + 2  # Строки в Google Sheets начинаются с 1
        sheet.values().clear(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A{start_row}:Z'
        ).execute()

        if non_empty_rows:
            sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A{start_row}',
                valueInputOption='RAW',
                body={'values': non_empty_rows}
            ).execute()
            logging.info(f"Данные ниже строки с текущей датой успешно обновлены, убраны пустые строки.")
        else:
            logging.info(f"Все строки ниже даты '{current_date_str}' оказались пустыми или между записями не было пустых строк.")

    except HttpError as err:
        logging.info(f"Ошибка при удалении пустых строк ниже {current_date_str}")

async def search_club_in_google(club_name, club_country, context):
    """
    Ищет название футбольного клуба в Google, переходит по первой ссылке и извлекает общую стоимость команды.
    """
    # Разбиваем название клуба на части
    parts = club_name.lower().split(" ")

    # Добавляем "fc" в конец, если его нет в названии
    if "fc" not in parts:
        modified_club_name = club_name + " " + "fc"
    else:
        modified_club_name = club_name

    # Открываем новую вкладку в браузере
    page = await context.new_page()

    try:
        # Формируем URL для поиска
        google_url = f"https://www.google.com/search?q={modified_club_name.replace(' ', '+')}+transfermarkt+{club_country.lower().replace(' ', '+')}&hl=en"
        logging.info(f"Поиск клуба {club_name} в гугле по ссылке: {google_url}")

        # Переход на страницу Google
        await page.goto(google_url)

        # Ждем, пока результаты загрузятся
        await page.wait_for_selector("#search", timeout=5000)

        # Извлечение первой ссылки из результатов поиска
        try:
            first_result = await page.query_selector("div.yuRUbf a")
            if not first_result:
                logging.warning(f"Transfermarkt ссылка на клуб {club_name} не найденна.")
                return None

            # Получаем ссылку
            first_result_url = await first_result.get_attribute("href")

            # Переход на первую ссылку
            await page.goto(first_result_url)
            logging.info(f"Переход на страницу комманды {club_name}: {first_result_url}")

            # Ждем загрузки страницы
            await page.wait_for_selector("a.data-header__market-value-wrapper", timeout=8000)

            # Извлечение общей стоимости команды
            market_value_element = await page.query_selector("a.data-header__market-value-wrapper")
            if market_value_element:
                market_value = await market_value_element.inner_text()
                logging.info(f"Общая стоимость команды {club_name}: {market_value}")
                return market_value.split("\n")[0]
            else:
                logging.info(f"Общая стоимость команды {club_name} не найдена на странице.")
                return None

        except Exception as e:
            logging.info(f"Ошибка при переходе на страницу сайта клуба или извлечении данных")
            return None

    finally:
        # Закрываем вкладку
        await page.close()


def find_chrome_executable():
    """
    Ищет путь к chrome.exe в системе.
    Возвращает полный путь, если найден, иначе вызывает исключение.
    """
    # Поиск в стандартных папках для Windows
    possible_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # Если стандартные пути не подходят, ищем в PATH
    chrome_path = shutil.which("chrome")
    if chrome_path:
        return chrome_path

    raise FileNotFoundError("Не удалось найти chrome.exe. Убедитесь, что Google Chrome установлен.")


async def scrape_flashscore(next_day=False):
    async with async_playwright() as p:
        # Инициализируем браузер и страницу
        #exrcutable path можно указать оббой хромиум

        try:
            browser = await p.chromium.launch(executable_path=find_chrome_executable(), headless=False,
            args=["--disable-blink-features=AutomationControlled"])
        except Exception as e:
            logging.error(f"Не удалось найти chrome.exe. Убедитесь, что Google Chrome установлен.")
            return
        context = await browser.new_context()
        page = await context.new_page()

        # Открываем сайт
        url = "https://www.flashscore.com/"
        await page.goto(url)
        #authorithation
        try:
            # Клик на кнопку "LOGIN"
            login_button = await page.wait_for_selector("#user-menu", timeout=15000)
            await login_button.click()

            # Ожидаем появления формы логина
            await page.wait_for_selector(".lsidDialog--login", timeout=15000)

            # Клик на кнопку "Continue with email"
            email_button = await page.wait_for_selector("button.social__button.email", timeout=15000)
            await email_button.click()

            # Ввод email
            email_input = await page.wait_for_selector("input#email", timeout=15000)
            await email_input.fill(config["user_email"])  # Замените на ваш email

            # Ввод пароля
            password_input = await page.wait_for_selector("input#passwd", timeout=15000)
            await password_input.fill(config["password"])  # Замените на ваш пароль

            # Нажатие на кнопку "Log In"
            login_submit_button = await page.wait_for_selector("button.lsidDialog__button", timeout=15000)
            await login_submit_button.click()

            # Проверка, выполнен ли вход
            await page.wait_for_selector(".header__text--loggedIn", timeout=8000)
            logging.info("Авторизация через email прошла успешно!")

        except Exception as e:
            logging.error(f"Ошибка при авторизации, проверьте email и пароль")
            return



        logging.info("Пользователь авторизован. Начинаем сбор данных...")
        # Шаг 1: Переключение на вкладку "Odds"
        try:
            odds_tab = await page.wait_for_selector("//div[contains(@class, 'filters__tab') and .//div[text()='Odds']]",
                                                    timeout=8000)
            await odds_tab.click()

            # Ожидание обновления содержимого
            await page.wait_for_selector(".event__match", timeout=10000)
            logging.info("Переключились на вкладку 'Odds'.")
        except Exception as e:
            logging.warning("Ошибка при переключении на 'Odds':")
            await browser.close()
            return
        if next_day:
            try:
                # Ждем появления кнопки на странице
                tomorrow_button = await page.wait_for_selector(
                    "button.calendar__navigation--tomorrow", timeout=5000
                )

                # Клик по кнопке
                await tomorrow_button.click()
                logging.info("Кнопка 'Next day' нажата успешно.")

                # Дожидаемся обновления динамического контента
                await page.wait_for_selector(".event__match", timeout=10000)

            except Exception as e:
                logging.warning(f"Ошибка при нажатии на кнопку 'Next day'")

        # Шаг 2: Извлечение данных о лигу и стране
        try:
            # Получаем все ссылки на лиги
            league_links = await page.query_selector_all("a.leftMenu__href")

            # Словарь для хранения стран и лиг
            countries_leagues = {}

            for link in league_links:
                href = await link.get_attribute("href")
                if href and href.startswith("/football/"):
                    # Разделяем строку href
                    parts = href.split("/")[2:4]  # Извлекаем страну и лигу
                    if len(parts) == 2:
                        country = parts[0]
                        league = parts[1].title().strip().lower()  # Преобразуем название лиги

                        # Если страна уже есть в словаре, добавляем лигу, если нет - создаем новый список
                        if country not in countries_leagues:
                            countries_leagues[country] = [league]
                        else:
                            countries_leagues[country].append(league)


        except Exception as e:
            logging.warning(f"Ошибка при извлечении данных о лиге и стране из закрепленных лиг")

        # Шаг 2: Извлечение пар команд
        try:
            matches = await page.query_selector_all(".event__match")
            match_pairs = []
            for match in matches:
                # Извлекаем URL для матча
                match_link_element = await match.query_selector("a")
                match_link = await match_link_element.get_attribute("href")

                participants = await match.query_selector_all(".event__participant")
                K1 = await participants[0].inner_text()
                K2 = await participants[1].inner_text()

                try:
                    # Находим элемент с классом odds__odd
                    odds = await match.query_selector_all(".odds__odd")
                    odds_values = []
                    for odd in odds:
                        odd_value = None
                        # Проверяем, содержит ли odd элемент <span>
                        span_elements = await odd.query_selector_all("span")
                        if span_elements:
                            span_text = await span_elements[0].inner_text()
                            odd_value = float(span_text.strip().replace(",", "."))  # Меняем запятую на точку

                            odds_values.append(odd_value)
                        else:
                            logging.warning(f"Не найденны коэфициенты на матч {K1} - {K2}.")


                    if len(odds_values) > 1:
                        excluded_value = odds_values[1]  # Второй элемент
                        odds_values = [value for i, value in enumerate(odds_values) if i != 1]

                    if odds_values:  # Проверяем, что список odds_values не пуст
                        odd_value = min(odds_values)  # Берем минимальное значение из списка
                        logging.info(f"Минимальный коэфициент  для матча {K1} - {K2}: {odd_value}")
                    else:
                        logging.warning(f"Минимальный коэфициент не найде для матча {K1} - {K2}")
                        odd_value = None
                        #???????????
                        continue
                except Exception as e:
                    logging.warning(f"Ошибка при поиске минимального коэфициента для матча {K1} - {K2}")
                    continue

                # Добавляем информацию о матче и ставках в список
                if odd_value < 1.75:
                    # Открываем страницу матча
                    new_page = await context.new_page()
                    await new_page.goto(match_link)

                    try:
                        page_league = await new_page.query_selector(".tournamentHeader__country")
                        league_info = str(await page_league.inner_text()).split("-")[0].split(":")
                        match_country = league_info[0].strip()
                        league_name = league_info[1].strip()

                        # Нормализация данных
                        normalized_match_country = match_country.lower().replace(" ", "-").strip()
                        normalized_league_name = league_name.lower().replace(" ", "-").replace(".","").strip()

                        # Проверка на наличие страны и лиги
                        if normalized_match_country not in countries_leagues.keys() or \
                                normalized_league_name not in countries_leagues.get(normalized_match_country, []):
                            logging.info(f"Лига {league_name} или страна {match_country} не из pinned leagues, завершение сбора информации")
                            await new_page.close()
                            break

                    except Exception as e:
                        logging.warning(f"Ошибка при поиске лиги или страны матча {K1} - {K2}")
                        await new_page.close()
                        continue

                    # Шаг: Переход к "Odds" -> "Over/Under"
                    try:
                        odds_comparison_button = await new_page.wait_for_selector(
                            "//a[@href='#/odds-comparison']/button", timeout=2000)
                        await odds_comparison_button.click()

                        over_under_link = await new_page.wait_for_selector("//a[@href='#/odds-comparison/over-under']",
                                                                           timeout=2000)
                        await over_under_link.click()

                        # Шаг 4: Извлечение данных из таблицы
                        table_body = await new_page.wait_for_selector(".oddsTab__tableWrapper", timeout=2000)

                        rows = await table_body.query_selector_all(".ui-table__row")
                        for row in rows:
                            # Проверяем наличие нужного значения в oddsCell__odd
                            odd_cell = await row.query_selector(".oddsCell__noOddsCell")
                            if float(await odd_cell.inner_text()) == 2.5:
                                odds_value_element = await row.query_selector(".oddsCell__odd")
                                over_value = Decimal((await odds_value_element.inner_text()).strip().replace(",", "."))
                                logging.info(f"{K1} - {K2} Over 2.5 : {over_value}")
                                break

                        # Попытка кликнуть на вкладку "1st Half"
                        first_half_tab = await new_page.wait_for_selector("//a[@title='1st Half']", timeout=2000)
                        await first_half_tab.click()

                        # Извлечение пeрвой строки таблицы
                        first_row = await new_page.wait_for_selector(".ui-table__row", timeout=2000)
                        first_time = await first_row.query_selector(".oddsCell__odd")
                        first_half = await first_time.query_selector("span")
                        logging.info(f"{K1} - {K2} 1st Half: {await first_half.inner_text()}")
                        first_time_value = Decimal((await first_half.inner_text()).strip().replace(",", "."))

                    except Exception as e:
                        logging.warning(f"Ошибка при обработке страницы матча {match_link}")
                    finally:
                        # Закрываем вкладку и возвращаемся на главную страницу
                        await new_page.close()

                    k1_fullname = await search_club_in_google(K1, match_country, context)
                    k2_fullname = await search_club_in_google(K2, match_country, context)
                    logging.info(f"{K1} total value: {k1_fullname}")
                    logging.info(f"{K2} total value: {k2_fullname}")

                    match_pairs.append({
                                "K1": K1,
                                "K2": K2,
                                "odds": odd_value,
                                "over": over_value,
                                "first_time": first_time_value,
                                "match_country": match_country,
                                "league_name": league_name,
                                "total_k1": k1_fullname,
                                "total_k2": k2_fullname
                            })

            logging.info(f"Найдено матчей: {len(match_pairs)}")

        except Exception as e:
            logging.warning(f"Ошибка при обработке главной страницы Flashscore")
        # Завершаем работу браузера
        await browser.close()
        return match_pairs

def evening_scraping():
    logging.info(f"[{datetime.now()}] Запуск вечернего сбора данных...")
    match_pairs = asyncio.run(scrape_flashscore(next_day=True))
    update_google_sheet(spreadsheet_id, match_pairs, next_day=True)

def morning_scraping():

    logging.info(f"[{datetime.now()}] Запуск утреннего сбора данных...")
    match_pairs = asyncio.run(scrape_flashscore())
    update_matches_in_google_sheet(spreadsheet_id, match_pairs)
    remove_empty_rows_below_date()

# schedule.every().day.at(config["evening_time"]).do(evening_scraping)
# schedule.every().day.at(config["morning_time"]).do(morning_scraping)
#
# while True:
#     schedule.run_pending()
#     time.sleep(1)

import tkinter as tk
from tkinter import messagebox

def save_config(data, config_file=CONFIG_FILE):
    try:
        with open(config_file, "w") as file:
            json.dump(data, file, indent=4)
        logging.info("Данные успешно записаны в config.json")
        # Проверка содержимого файла
        with open(config_file, "r") as file:
            logging.info(f"Содержимое config.json после записи: {file.read()}")
    except Exception as e:
        logging.error(f"Ошибка при сохранении конфигурации в config.json файл")
        raise


# Функция для обработки кнопки "Сохранить"
def save_data():
    global config
    new_config = {
        "sheet_id": sheet_id_entry.get(),
        "user_email": email_entry.get(),
        "password": password_entry.get(),
        "evening_time": evening_time_entry.get(),
        "morning_time": morning_time_entry.get(),
    }
    # Сохраняем в файл и обновляем глобальную переменную
    save_config(new_config)
    config = new_config
    messagebox.showinfo("Успешно", "Данные сохранены.")

def on_close():
    # При закрытии окна предлагаем сохранить изменения
    if messagebox.askyesno("Выход", "Вы хотите сохранить изменения перед выходом?"):
        save_data()
    app.destroy()




app = tk.Tk()
app.title("Flashscore-Trasfermarket scraper")
app.geometry("600x300")

tk.Label(app, text="Google Sheet ID:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
sheet_id_entry = tk.Entry(app, width=50)
sheet_id_entry.grid(row=0, column=1, padx=10, pady=5)
sheet_id_entry.insert(0, config.get("sheet_id", ""))

tk.Label(app, text="Email:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
email_entry = tk.Entry(app, width=50)
email_entry.grid(row=1, column=1, padx=10, pady=5)
email_entry.insert(0, config.get("user_email", ""))

tk.Label(app, text="Пароль:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
password_entry = tk.Entry(app, width=50, show="*")
password_entry.grid(row=2, column=1, padx=10, pady=5)
password_entry.insert(0, config.get("password", ""))

tk.Label(app, text="Время утреннего сбора (ЧЧ:ММ):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
morning_time_entry = tk.Entry(app, width=50)
morning_time_entry.grid(row=3, column=1, padx=10, pady=5)
morning_time_entry.insert(0, config.get("morning_time", "08:00"))

tk.Label(app, text="Время вечернего сбора (ЧЧ:ММ):").grid(row=4, column=0, padx=10, pady=5, sticky="w")
evening_time_entry = tk.Entry(app, width=50)
evening_time_entry.grid(row=4, column=1, padx=10, pady=5)
evening_time_entry.insert(0, config.get("evening_time", "18:00"))

save_button = tk.Button(app, text="Сохранить", command=save_data)
save_button.grid(row=5, column=0, columnspan=2, pady=20)


def scheduler():
    while True:
        current_time = datetime.now().strftime("%H:%M")

        # Проверка утреннего времени
        if current_time == config["morning_time"]:
            threading.Thread(target=morning_scraping).start()
            time.sleep(60)

        # Проверка вечернего времени
        elif current_time == config["evening_time"]:
            threading.Thread(target=evening_scraping).start()
            time.sleep(60)

        time.sleep(1)

# Функция для запуска планировщика в отдельном потоке
def start_scheduler():
    threading.Thread(target=scheduler, daemon=True).start()

start_scheduler()
app.mainloop()
















