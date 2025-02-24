import threading
import socket
import json
import time
import dash
from datetime import datetime 
import pyodbc
from dash import dcc, html
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
from dash.dependencies import Input, Output

current_ticker = "AAPL"
current_strategy = "ema"
data_cache = {}  
client_socket = None

balance = 10000

# Класс для хранения сделок
class TradeResult:
    def __init__(self, action, price, amount, balance, timestamp):
        self.action = action  
        self.price = price 
        self.amount = amount  
        self.balance = balance  
        self.timestamp = timestamp

    def to_dict(self):
        return {
            "action": self.action,
            "price": self.price,
            "amount": self.amount,
            "balance": self.balance,
            "timestamp": self.timestamp
        }

# Класс для загрузки данных о компании
class StockData:
    def __init__(self, ticker):
        self.ticker = ticker
        self.data = self._load_data()

    def _load_data(self):
        if self.ticker in data_cache:
            print(f"Данные для {self.ticker} найдены в кэше.")
            return data_cache[self.ticker]
        
        print(f"Загружаем данные для {self.ticker}...")

        try:
            data = yf.download(self.ticker, start="2023-01-01", end="2025-01-01")
            if data.empty:
                raise ValueError(f"Нет данных для {self.ticker}.")
            data["EMA"] = data["Close"].ewm(span=20, adjust=False).mean()
            data["MA"] = data["Close"].rolling(window=20).mean()
            data_cache[self.ticker] = data
            print(f"Данные для {self.ticker} успешно загружены.")
            return data
        except Exception as e:
            print(f"Ошибка при загрузке данных для {self.ticker}: {e}")
            return pd.DataFrame()

    def get_data(self):
        return self.data

# Класс для создания графиков стоимости акций и запуска Dash сервера в отдельном потоке
class Chart:
    def __init__(self):
        self.ticker = current_ticker
        self.strategy = current_strategy
        self.app = dash.Dash(__name__)
        self.fig = go.Figure()
        self.app.layout = html.Div([
            html.H1(f"Stock Chart"),
            dcc.Graph(id='live-graph', figure=self.fig),
            dcc.Interval(id='interval-component', interval=10*1000, n_intervals=0)  # Обновление каждые 10 секунд
        ])

        @self.app.callback(
            Output('live-graph', 'figure'),
            Input('interval-component', 'n_intervals')
        )
        def update_graph(n):
            return self.create_chart()

    def create_chart(self):
        stock_data = StockData(current_ticker)
        data = stock_data.get_data()

        if data.empty:
            print(f"Нет данных для {self.ticker}")
            return self.fig

        self.fig = go.Figure()
        self.fig.add_trace(go.Scatter(
                x=data.index,
                y=data['EMA'],
                marker_color='blue',
                name='20 Day EMA'
        ))
        
        if self.strategy == "ema":
            self.fig.add_trace(go.Scatter(
                x=data.index,
                y=data['EMA'],
                marker_color='blue',
                name='20 Day EMA'
            ))
        elif self.strategy == "ma":
            self.fig.add_trace(go.Scatter(
                x=data.index,
                y=data['MA'],
                marker_color='green',
                name='20 Day MA'
            ))

        return self.fig

    def run_dash(self):
        print("Dash сервер запущен на http://127.0.0.1:8050")
        self.app.run_server(debug=False, use_reloader=False, port=8050)

    def start_chart_thread(self):
        chart_thread = threading.Thread(target=self.run_dash, daemon=True)
        chart_thread.start()
# Класс для взаимодействия с C++ и обмена данными с ним. Обновление параметров. 
# Загрузка сделок в базу данных
class SocketServer:
    def __init__(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(("localhost", 12346))
        self.server_socket.listen(5)
        self.conn = None
        self.db_conn = None
        self.connect_to_db()
        print("Python server listening on port 12346...")

    # Запуск сервера и обработка сообщений в отдельном потоке
    def start_server(self):
        while True:
            self.conn, addr = self.server_socket.accept()
            print(f"Connected by {addr}")

            threading.Thread(target=self.handle_client, daemon=True).start()

    def handle_client(self):
        global current_ticker, current_strategy

        while True:
            try:
                data = self.conn.recv(1024)
                if not data:
                    print("Client disconnected")
                    break

                message = json.loads(data.decode("utf-8"))
                print(f"Received from C++: {message}")

                if message.get("type") == "company":
                    current_ticker = message.get("value")
                    StockData(current_ticker)  
                    print(f"Компания изменена на: {current_ticker}")
                elif message.get("type") == "strategy":
                    current_strategy = message.get("value")
                    print(f"Стратегия изменена на: {current_strategy}")

            except Exception as e:
                print(f"Ошибка при обработке данных: {e}")
                break

        self.conn.close()

    # Подключение к базе данных
    def connect_to_db(self):
        try:
            server = '172.18.48.1,1433'
            database = 'trading_db'
            driver = '{ODBC Driver 17 for SQL Server}'

            # Строка подключения
            conn_str = (
                f'DRIVER={driver};'
                f'SERVER={server};'
                f'DATABASE={database};'
                f'UID=sa;'
                f'PWD=56978;'
            )

            self.db_conn = pyodbc.connect(conn_str)
            cursor = self.db_conn.cursor()

            cursor.execute("SELECT @@version;")
            row = cursor.fetchone()
            print("Подключение успешно! Версия SQL Server:", row[0])
        except pyodbc.Error as e:
            print(f"Ошибка подключения к БД: {e}")
            self.db_conn = None
    # Восстановление подключения к базе данных
    def ensure_db_connection(self):
        if self.db_conn is None:
            self.connect_to_db()

    def save_to_db(self, trade_result):
        self.ensure_db_connection()

        if self.db_conn:
            cursor = self.db_conn.cursor()
            try:
                timestamp_str = trade_result["timestamp"]
                try:
                    datetime_obj = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                except ValueError as e:
                    print(f"Ошибка в формате timestamp: {timestamp_str}. Ожидается 'YYYY-MM-DD HH:MM:SS'.")
                    return

                cursor.execute("""
                    INSERT INTO trade (action, price, amount, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (trade_result["action"], trade_result["price"], trade_result["amount"], datetime_obj))

                self.db_conn.commit()
                print("Сделка сохранена в MSSQL")
            except Exception as e:
                print(f"Ошибка сохранения в MSSQL: {e}")
        else:
            print("Нет подключения к базе данных")

    def send_results(self, trade_result):
        if self.conn is None:
            print("Соединение с клиентом не установлено.")
            return

        results = trade_result.to_dict()
        self.save_to_db(results)
        print(f"📤 Сохранено в MSSQL и отправлено в C++: {results}")

        try:
            self.conn.send(json.dumps(results).encode("utf-8"))
        except Exception as e:
            print(f"Ошибка при отправке данных: {e}")
            self.conn.close()
            self.conn = None
# Класс для реализации стратегий
class Strategy:
    """Базовый класс стратегий"""
    def __init__(self, ticker):
        self.ticker = ticker

    def get_stock_data(self, timeout=30):
        start_time = time.time()
        while self.ticker not in data_cache:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Данные для {self.ticker} не загружены в течение {timeout} секунд.")
            time.sleep(1)
            print("Ожидаем данные...")
        
        print(f"Данные для {self.ticker} теперь в кеше!")
        return data_cache[self.ticker]

    def execute(self):
        raise NotImplementedError("Метод execute() должен быть реализован в подклассе!")

# Реализация стратегии EMA
class EmaStrategy(Strategy):
    def execute(self):
        global balance
        try:
            data = self.get_stock_data() 
        except TimeoutError as e:
            print(e)
            return None

        if data.empty:
            return None
        
        latest_price = data["Close"].iloc[-1]
        ema = data["EMA"].iloc[-1]
        if isinstance(latest_price, pd.Series):
            latest_price = latest_price.item()
        
        if isinstance(ema, pd.Series):
            ema = ema.item()  
        if latest_price > ema:
            trade_result = TradeResult(action="BUY", price=latest_price, amount=10, balance=balance, timestamp=time.strftime("%Y-%m-%d %H:%M:%S"))
            balance -= latest_price * 10
        else:
            trade_result = TradeResult(action="SELL", price=latest_price, amount=10, balance=balance, timestamp=time.strftime("%Y-%m-%d %H:%M:%S"))
            balance += latest_price * 10
        
        return trade_result 
    

if __name__ == "__main__":

    StockData(current_ticker)

    server = SocketServer()
    server_thread = threading.Thread(target=server.start_server, daemon=True)
    server_thread.start()

    chart = Chart()
    chart.start_chart_thread()

    while True:
        ema_strategy = EmaStrategy(current_ticker)
        trade_result = ema_strategy.execute()
        if trade_result:
            server.send_results(trade_result)
        time.sleep(10) 