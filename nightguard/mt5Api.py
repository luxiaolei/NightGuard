
from logging import log
import warnings

warnings.filterwarnings('ignore')

from datetime import time, datetime, timedelta
from time import sleep
from queue import Queue, PriorityQueue
from threading import Thread
from pathlib import Path
from configobj import ConfigObj

import MetaTrader5 as mt5 
import pandas as pd 

from . import PAK_DIR, logging


class MT5Api:
    """A Class that wraps Metatrader5 functionalities. 

    datetime and time are all the same as broker's time. 

    Methods:
        get_market_close_dt: returns `datetime` of market for current week, shifted by `min_before`
        get_market_open_dt: returns `datetime` of market open for current week
    """

    @staticmethod
    def get_market_close_dt(min_before=2):
        """returns `datetime`(Broker GMT) of market for current week, shifted by `min_before`

        Args:
            min_before (int, optional): shift number of minutes before. Defaults to 2.

        Returns:
            datetime: datetime of market close
        """
        # doesnt requires mt5, return 1 minutes before
        today = datetime.now().date() + timedelta(1)
        friday = today + timedelta( (4-today.weekday()) % 7 )
        market_close_dt = datetime.combine(friday, datetime.min.time()) + timedelta(hours=23, minutes=55)
        if min_before >= 0:
            return market_close_dt - timedelta(minutes=min_before)
        else:
            return market_close_dt + timedelta(minutes=abs(min_before))
            
    @staticmethod
    def get_market_open_dt(min_after=0):
        '''Return dt of market open, If make comparison, required to request mt5 '''
        return MT5Api.et_market_close_dt(min_before=-5-min_after) + timedelta(days=2)


    def __init__(self, config_path=PAK_DIR/'Config.ini') -> None:
        """Login to account and checking market time condition.

        When initiaized, it logging first and check if its weekend, if it is, it promote
        to user for manually input the gmt shift. then wait until market open.

        Args:
            config_path (str, optional): path to Config.ini file. Defaults to PAK_DIR/'Config.ini'.
        """
        self.conf = ConfigObj(config_path.as_posix())['Auth']
        self.login()
        
        if not self.check_market_is_open():
            hour_shift = input(f'\n>>> Market is closed, please manually type the hour shift of your broker: ')
            self._time_delta = timedelta(hours=int(hour_shift))
            market_open_dt = self.get_market_open_dt()
            delta_till_open = self.broker_time_local() - market_open_dt
            logging.info(f'Current broker time: {self.broker_time_local()} Market open time {market_open_dt}')
            logging.info(f'Sleeping {round(delta_till_open.seconds/3600, 2)} Hours and 10 secs..')
            sleep(delta_till_open.seconds + 10)
            logging.info(f'Woke up!')
            self.__init__(config_path=config_path)
        else:
            self._time_delta = self.broker_time - datetime.utcnow() 
            hour_shift = round(self._time_delta.seconds / 3600)
        logging.info(f'Hours difference between UTC time and Broker time is {hour_shift}')
        
    @property
    def TEST_MODE(self):
        """In TEST MODE, close/open positions are fobidend

        Returns:
            bool: true for yes
        """
        return self.conf.as_bool('TEST')

    @property
    def broker_time_local(self):
        """Returns broker time calculated locally

        Returns:
            datetime: datetime of current calculated broker time 
        """
        return self._time_delta + datetime.utcnow()

    @property
    def broker_time(self):
        """Each call returns datetime from broker

        Returns:
            datetime: datetime of EURUSD 
        """
        sec = mt5.symbol_info_tick('EURUSD').time
        return pd.to_datetime(sec, unit='s')

    @property
    def cur_open_position_ids(self):
        """Returns current open positions IDs

        Returns:
            list: current open position ids
        """
        return [pos.identifier for pos in self.cur_positions]


    @property
    def cur_positions(self):
        """Return current open positions
        """
        try:
            return mt5.positions_get()
        except:
            logging.warning(f'Error when get current positions, mt5 error: {mt5.last_error()}')
            return []


    def login(self):
        """Login mt5 account, rase Error if not succeessed
        """
        mt5.initialize(Path(self.conf['mt5_exe_path']).as_posix())
        authorized=mt5.login(self.conf.as_int('login'), password=self.conf['password'], server=self.conf['server'])

        if authorized: 
            account_info=mt5.account_info() 
            if account_info!=None: 
                account_info_dict = mt5.account_info()._asdict() 
                for prop in account_info_dict: 
                    logging.info("  {}={}".format(prop, account_info_dict[prop])) 
                print() 
        else: 
            raise ValueError("Failed to connect to trade account error code =",mt5.last_error()) 


    def sec_to_dt(self, time_in_sec):
        """Returns datetime from seconds

        Args:
            time_in_sec (int): seconds started from 1970-1-1
        """
        return pd.to_datetime(time_in_sec, unit='s')

    def check_market_is_open(self):
        """Return a bool value indicates is market open or not

        By checking the tick time of EURUSD in an interval of 5 seconds
        
        Returns:
            bool: true for open, false for closed
        """
        logging.info('Checking is market open... ')
        t1 = mt5.symbol_info_tick('EURUSD').time
        if pd.to_datetime(t1, unit='s').weekday() <= 4: 
            return True
        sleep(10)
        t2 = mt5.symbol_info_tick('EURUSD').time
        if (t1 == t2) and (t1.time() == time(23,54,59)):
            logging.info(' Market is closed!')
            return False
        else:
            logging.info(' Market is open!')
            return True

    def get_price_to_close(self, position):
        """Return the price if close the `position`

        Args:
            position (positon): position to close
        """
        tick = mt5.symbol_info_tick(position.symbol)
        volume = position.volume if position.type == 0 else -position.volume
        ex_price = tick.bid if volume > 0 else tick.ask
        return ex_price

    def get_bar(lb=10):
        """Return M1 bar dataframe with `lb` looklack period. Index sorted by datetime

        Args:
            lb (int, optional): look back period. Defaults to 10.

        Returns:
            dataframe: bar dataframe indexed by broker time, with columns ['open', 'high', 'low', 'close]
        """
        rates = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_M1, 0, lb+1) 
        rates_frame = pd.DataFrame(rates) 
        rates_frame.index = pd.to_datetime(rates_frame['time'], unit='s') 
        return rates_frame

    def get_m1_timmer_Q(self):
        """
        Start a thread that continuesly push a datetime object into a queue when 
        a minute finished, The queue has size 1, with element of current datetime 
        of M1 minute bar which can use as loc bars.

        It makes sure the most recent 1 minute is finished. 
        put the datetime into `q`, which has 0 seconds It runs indefinitely.
        """
        q = Queue(maxsize=1)
        def _m1_timmer(self, q):
            """target function of processing m1 bar minute"""
            while True:
                last_minute = self.broker_time.time().minute
                while True:
                    cur_time = self.broker_time.time()
                    second = cur_time.second
                    if second < 2:
                        sleep(57)

                    cur_dt = self.broker_time 
                    if  cur_dt.time().minute > last_minute:
                        # cur minute has run at least 57 seconds. so its the most recent minute
                        if cur_dt.second < 30: 
                            full_dt = cur_dt.replace(minute=cur_dt.minute-1, second=0)
                            
                        else:
                            full_dt = cur_dt.replace(second=0)
                        q.put(full_dt)
                        break
        m1_timmer_T = Thread(target=_m1_timmer, args=(self, q,))
        m1_timmer_T.start()
        return q
            
                
    def close_position(self, position, comment='NightGuard'):
        """Close position with market order

        Args:
            position (MT5 Position): position object, which to close

        Returns:
            bool: indicates closed successfully or not
        """
        assert not self.TEST_MODE, f'TEST MODE forbid close position!'
        request={ 
            "action": mt5.TRADE_ACTION_DEAL, 
            "symbol": position.symbol, 
            "volume": position.volume, 
            "type": mt5.ORDER_TYPE_SELL if position.type==0 else mt5.ORDER_TYPE_BUY, 
            "position": position.identifier, 
            "magic": position.magic, 
            "comment": comment, 
            "type_time": mt5.ORDER_TIME_GTC, 
            "type_filling": mt5.ORDER_FILLING_IOC, 
        } 
        # send a trading request 
        result=mt5.order_send(request)
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            if result.retcode == 10027:
                logging.warn(f'AutoTrading disabled!')
            logging.error(f"  order_send failed, retcode={result.retcode}") 
            print(result)
            return False
        else:
            #self.trigger_closed_positions += [position]
            return True


        
    def get_timmer_Qs(self):
        '''
        It schedules datetime priortized tasks. Useful for time based actions. 
        A thread runs infidinitely when calling.

        It uses two queues, a PriortyQueue for put tasks which has time order,
        a normal FIFO queue for get the task. The out put task always get in 
        time order.
        
        pq is a PriortyQueue, element of it is a two length tuple, where the 
        first element needs to be datetime type, the second is a dict specifies
        the task type.
        
        Example:
            pq.put((pd.to_datetime('2021-2-1'), {'task': 'close'})) # 3rd,
            pq.put((pd.to_datetime('2021-2-1'), {'task': 'close'})) # 2nd, 
            pq.put((pd.to_datetime('2021-1-1'), {'task': 'news'})) #1st
            pq.put((pd.to_datetime('2021-5-1'), {'task': 'weekend'})) # last
        '''
        pq_in = PriorityQueue()
        q_out = Queue()
        
        def _get_and_wait(pq_in, q_out):
            while True:
                (task_dt, task) = pq_in.get()
                # Calculate the wait time
                cur_dt = self.broker_time_local
                
                if cur_dt > task_dt:
                    overdue_sec = (cur_dt - task_dt).seconds
                    logging.warn(f'Task {task} overdue!')
                    if overdue_sec >= 5*60:
                        logging.warn(f'  Skip: overdue {overdue_sec}s, should be excuded at {task_dt}, but now is {cur_dt}')
                        continue
                    else:
                        # Excute immediately
                        logging.warn(f'  Excute: overdue {overdue_sec}s')
                        q_out.put((task_dt, task))
                else:
                    wait_sec = (task_dt - cur_dt).seconds - 1 # Extra 1s conpensate the excution time
                    logging.info(f'{task} wait to be excuted. Wait seconds {wait_sec}')
                    sleep(max(wait_sec, 0))
                    q_out.put((task_dt, task))
        t = Thread(target=_get_and_wait, args=(pq_in, q_out,))
        t.start()
        return pq_in, q_out

    def get_history_positions(self, date_from, date_to=None):
        """        Return positions dataframe indexed by position id, columns are:

        ['En_Time', 'En_Price', 'Volume', 'symbol', 'magic', 'comment',
        'en_reason', 'Ex_Time', 'Ex_Price', 'profit', 'swap', 'ex_reason',
        'commision']

        for `reason` >= 3 are excuted by EA, actual description 
        see: https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties

        Args:
            date_from (str or datetime): date for start of history
            date_to (str or datetime, optional): date for end of history. Defaults to today.

        Returns:
            dataframe: retrieved histoies.
        """

        if isinstance(date_from, str): date_from = pd.to_datetime(date_from)
        if isinstance(date_to, str): date_to = pd.to_datetime(date_to)
        if date_to is None: date_to = self.broker_time()
        position_deals = mt5.history_deals_get(date_from, date_to)
        deals_df = pd.DataFrame(list(position_deals),columns=position_deals[0]._asdict().keys()) 

        # Filt out non buy and sell deals
        deals_df = deals_df[deals_df.type.isin([0,1])]
        deals_df['time'] = pd.to_datetime(deals_df.time, unit='s')

        # Select deals with only closed positions
        pid_size = deals_df.groupby('position_id').size()
        closed_pids = pid_size[pid_size==2].index
        deals_df = deals_df[deals_df.position_id.isin(closed_pids)]

        rename_cols = {
            'time': 'En_Time',
            'price': 'En_Price',
            'reason': 'en_reason',
            'commission': 'en_comm'
        }
        deal_in = deals_df[deals_df.entry==0]
        deal_in['type'] *= -1
        deal_in.loc[deal_in.type==0, 'type'] = 1
        deal_in['Volume'] = deal_in.volume * deal_in.type
        deal_in.rename(columns=rename_cols, inplace=True)
        deal_in.index = deal_in.position_id
        deal_in = deal_in[['En_Time', 'En_Price', 'Volume', 'symbol', 'en_comm', 'magic', 'comment', 'en_reason']]
        
        rename_cols = {
            'time': 'Ex_Time',
            'price': 'Ex_Price',
            'reason': 'ex_reason',
            'commission': 'ex_comm'
        }
        deal_out = deals_df[deals_df.entry==1]
        deal_out.rename(columns=rename_cols, inplace=True)
        deal_out.index = deal_out.position_id
        deal_out = deal_out[['Ex_Time', 'Ex_Price', 'profit', 'ex_comm', 'swap', 'ex_reason']]
        deal_out.head()

        positions = deal_in.join(deal_out)
        positions['commision'] = positions.en_comm + positions.ex_comm
        positions.drop(columns=['en_comm', 'ex_comm'], inplace=True)
        logging.debug(f'{len(positions)} positions retrieved from mt5, dt range {date_from} - {date_to}')
        return positions