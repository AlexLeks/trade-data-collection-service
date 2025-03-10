import asyncio
import sys
from loguru import logger
from cryptofeed import FeedHandler
from decimal import Decimal
from cryptofeed.exchanges import BinanceFutures
from cryptofeed.defines import CANDLES
from datetime import datetime
import time

import aioch
from aioch import Client as AIOClickHouseClient
import clickhouse_driver
import yaml
#from asynch import connect


logger.remove()
logger.add(
    sys.stderr,
    colorize=True,
    format="<green>{time:HH:mm:ss:ms}</green> | <level>{message}</level>",
    level=10,
)

logger.add("./logs/data_collector.log", rotation="1 MB", level="DEBUG", compression="zip")


def create_database_if_not_exists() -> None:
    '''Creates the binance_data database if it doesn't exist.'''
    with clickhouse_driver.Client(host='clickhouse',user=USER, password=PASSWORD, port=9000) as ch:
        ch.execute('CREATE DATABASE IF NOT EXISTS binance_data')
        logger.info('CREATE DATABASE IF NOT EXISTS binance_data')

def create_table_if_not_exists() -> None:
    '''Creates the binance_data.candles table if it doesn't exist.'''
    query = '''
        CREATE TABLE IF NOT EXISTS binance_data.candles (
            exchange String,
            symbol String,
            start DateTime,
            stop DateTime,
            close_unixtime Float32,
            interval String,
            trades Int32,
            open Float32,
            close Float32,
            high Float32,
            low Float32,
            volume Float64,
            timestamp DateTime,
            receipt_timestamp DateTime
        ) ENGINE = ReplacingMergeTree(receipt_timestamp)
        ORDER BY (symbol, interval, start)
    '''
    with clickhouse_driver.Client(host='clickhouse', user=USER, password=PASSWORD, port=9000) as ch:
        ch.execute(query)
        logger.info('CREATE TABLE IF NOT EXISTS binance_data.candles')

async def candle_callback(candle, receipt_timestamp) -> None:
    """Callback function that stores candle data into ClickHouse.

    Args:
        candle: The candle data.
        receipt_timestamp: The receipt timestamp.

    """
    #logger.info(candle)

    exchange = candle.exchange
    symbol = candle.symbol
    start = datetime.fromtimestamp(candle.start)
    stop = datetime.fromtimestamp(candle.stop)
    interval = candle.interval
    trades = candle.trades
    open_price = Decimal(candle.open)
    close_price = Decimal(candle.close)
    high_price = Decimal(candle.high)
    low_price = Decimal(candle.low)
    volume = Decimal(candle.volume)
    #closed = (candle.closed)
    timestamp = datetime.fromtimestamp(candle.timestamp)
    #receipt_timestamp = receipt_timestamp
    
    query = '''
        INSERT INTO binance_data.candles 
        (exchange, symbol, start, stop, close_unixtime, interval, trades, open, close, high, low, volume, timestamp, receipt_timestamp)
        VALUES 
        (%(exchange)s, %(symbol)s, %(start)s, %(stop)s, %(close_unixtime)s, %(interval)s, %(trades)s, %(open)s, %(close)s, %(high)s, %(low)s, %(volume)s, %(timestamp)s, %(receipt_timestamp)s)
    '''

    ch = AIOClickHouseClient(host='clickhouse', user=USER, password=PASSWORD, port=9000,)
    await ch.execute(query, {'exchange': exchange, 'symbol': symbol, 'start': start, 'stop': stop, 'close_unixtime': candle.stop, 'interval': interval, 'trades': trades, 'open': open_price, 'close': close_price, 'high': high_price, 'low': low_price, 'volume': volume, 'timestamp': timestamp, 'receipt_timestamp': receipt_timestamp})


async def symbols_callback(candle, receipt_timestamp):
    ''' check new symbols lists'''
    new_symbols = list(set(BinanceFutures.symbols()))
    new_symbols = [symbol for symbol in new_symbols if "-USDT-PERP" in symbol]
    # logger.info(f'Update symbols')

    if len(set(symbols)) != len(set(new_symbols)):
        logger.info(f'!!! Change total symbols! old: {(len(set(symbols)))} new: {len(set(new_symbols))}')
        asyncio.sleep(5)
        asyncio.get_event_loop().stop()


if __name__ == '__main__':
    logger.info(f'Delay start by 10sec so that BD are ready')
    time.sleep(10)
    logger.info(f'start')

    ####### LOAD CONFIG #########################################################
    with open("config.yaml", 'r') as ymlfile:
        config = yaml.load(ymlfile, Loader=yaml.SafeLoader)

    SYMBOLS_TYPE = config['SYMBOLS_TYPE']
    TIMEFRAME = config['TIMEFRAME']

    USER = config['CLICKHOUSE_USER']
    PASSWORD = config['CLICKHOUSE_PASSWORD']

    # Set up the FeedHandler
    while True:
        logger.info(f'Start new loop')
        create_database_if_not_exists()
        create_table_if_not_exists()

        symbols = BinanceFutures.symbols()
        symbols = [symbol for symbol in symbols if SYMBOLS_TYPE in symbol]
        logger.info(f'Add symbols: {len(symbols)}')
        
        callbacks = {CANDLES: candle_callback}
        #binance = Binance(symbols=symbols, channels=[CANDLES,], callbacks=callbacks)

        f = FeedHandler()
        loop = asyncio.get_event_loop()
        #f.add_feed(binance)

        # try fix websockets.exceptions.ConnectionClosedErrorr
        for symbol in symbols:
            logger.info(f'ADD {symbol} feed')
            f.add_feed(BinanceFutures(symbols=[symbol,], channels=[CANDLES,], callbacks=callbacks, candle_interval=TIMEFRAME, candle_closed_only=True))

        f.add_feed(BinanceFutures(symbols=symbols[:1], channels=[CANDLES,], callbacks={CANDLES: symbols_callback}, candle_interval=TIMEFRAME, candle_closed_only=True))
        # Start the data collection
        f.run(start_loop=False)

        loop.run_forever()
        asyncio.sleep(5)
