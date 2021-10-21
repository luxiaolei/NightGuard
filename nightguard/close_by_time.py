
'''
py -m ensurepip --upgrade & py -m pip install pandas & py -m pip install MetaTrader5

'''
from threading import Thread
from datetime import datetime, time, timedelta
from time import sleep
from pytz import timezone
from pathlib import Path
import json

import MetaTrader5 as mt5 
import pandas as pd 

from pathlib import Path
PAK_DIR = Path(__file__).parent.parent.absolute().resolve()
print(f'Package Dir: {PAK_DIR}')

config_fn  = PAK_DIR / 'Config.txt'
report_fn = PAK_DIR / 'OpenPositionReport.csv'
symstop_fn = PAK_DIR / 'symbol_stopT.csv'

with open(config_fn.as_posix(), 'r') as f:
    config = f.readlines()
settings = {}
for line in config:
    if '=' in line:
        k,v = line.split('=')
        v = v.replace('\n','')
        if k not in ['mt5_exe_path', 'server', 'password']:
            v = int(v.replace(' ',''))
        settings[k] = v
print(settings)

TEST = settings['TEST']
if TEST:
    print('TEST MODE: Positions will not be closed by NightGuard.')
else:
    print('LIVE MODE: Positions can be closed by NightGuard.')

night_start_time = time(hour=settings['NS_START_HOUR'], minute=settings['NS_START_MINUTE'])
night_end_time  = time(hour=settings['NS_END_HOUR'], minute=settings['NS_END_MINUTE'])
        

mt5.initialize(settings['mt5_exe_path'])
authorized=mt5.login(settings['login'], password=settings['password'], server=settings['server'])

if authorized: 
    account_info=mt5.account_info() 
    if account_info!=None: 
        # display trading account data 'as is' 
        print(account_info) 
        # display trading account data in the form of a dictionary 
        print("Show account_info()._asdict():") 
        account_info_dict = mt5.account_info()._asdict() 
        for prop in account_info_dict: 
            print("  {}={}".format(prop, account_info_dict[prop])) 
        print() 

else: 
    raise ValueError("Failed to connect to trade account error code =",mt5.last_error()) 

 
def epoch_to_dt(epoch_sec):
    return datetime.fromtimestamp(epoch_sec, timezone('UTC'))

def total_seconds_between(st, et):
    return (et.minute*60 + et.hour*3600) - (st.minute*60 + st.hour*3600)


broker_gmt_shift = epoch_to_dt(mt5.symbol_info_tick('EURUSD').time).hour - datetime.utcnow().hour
print(f'Broker GMT to UTC Offset Hours: {broker_gmt_shift}')

class Tonight: 

    report_cols = ['symbol', 'magic', 'comment', 
               'volume', 'en_time', 'ex_time', 'en_price', 'ex_price', 'profit', 
               'profit_if', 'ex_time_if', 'ex_price_if']

    def __init__(self, mt5):
        self.mt5 = mt5
        self.threads = []
        self.sym_time_stopT = self._get_sym_stopT()

        self.report_fn =  report_fn
        if self.report_fn.exists():
            self.report_df = pd.read_csv(self.report_fn.as_posix(), index_col=0)
        else:
            self.report_df = pd.DataFrame(columns=self.report_cols)

        # Error manage
        self._error_fn = Path('error.txt')

        print(f'Start running Night scalper SafeGuard. Current Balance: {self.balance} @ {self.cur_dt}')
        print(f'  Night start time : {night_start_time} Cur time: {self.cur_dt.time()}')

        wait_secs = max(total_seconds_between(self.cur_dt, night_start_time) - 10, 10)
        sleep(wait_secs)
        while True:
            if self.cur_dt.time() >= night_start_time:
                self.start()
                break

    def _get_sym_stopT(self):
        sym_time_stopT = pd.read_csv(symstop_fn.as_posix(), index_col=0)
        sym_time_stopT['StopT'] = sym_time_stopT.StopT.apply(lambda t: pd.to_datetime(t).time())

        # Key is symbol, value is a list contains magic numbers 
        sym_magic_stopT = {}
        for sym, row in sym_time_stopT.iterrows():
            if pd.isna(row.Magic_start):
                if pd.isna(row.Magics):
                    print(f'  {sym} : ALL magics will be managed. Stop time {row.StopT}')
                    sym_magic_stopT[sym] = {
                        'StopT': row.StopT,
                        'Magics': list(range(-99999,99999))
                    }
                else:
                    magics = row.Magics if row.Magics[-1]!=';' else row.Magics[:-1]
                    magics = [int(i) for i in magics.split(';')]
                    print(f'  {sym} : Magics with {magics} will be managed. Stop time {row.StopT}')
                    sym_magic_stopT[sym] = {
                        'StopT': row.StopT,
                        'Magics': magics
                    }
            else:
                if pd.isna(row.Magic_end):
                    print(f'        ATTENTION {sym} Magic_start is given but Magic_end is empty.')
                    magic_range = [row.Magic_start]
                else:
                    magic_range = list(range(int(row.Magic_start), int(row.Magic_end)+1, 1))
                print(f'  {sym} : Magics with {magic_range} will be managed. Stop time {row.StopT}')
                sym_magic_stopT[sym] = {
                    'StopT': row.StopT,
                    'Magics': magic_range
                }
        return sym_magic_stopT


    def _check_mt5(self, ret):
        '''
        Check mt5 get/request methods return and append to error log.
        '''
        if ret == None:
            with open(self._error_fn.as_posix(), 'a+', newline='\n') as f:
                msg = f'SYS TIME {str(datetime.today())} : {self.mt5.last_error()}'
                print(msg)
                f.write(msg)
        return ret

    def start(self):
        self.start_time = self.mt5.symbol_info('EURUSD').time
        self.start_dt = self.cur_dt

        self.start_balance = self.balance
        self.trigger_closed_positions = []
        print(f'Night Start!  @ {self.start_dt} ')
        print(f'It will start guarding open positions @ {night_end_time}')

        wait_secs = max(total_seconds_between(self.cur_dt, night_end_time) - 10, 10)
        sleep(wait_secs)
        
        while True:
            if self.cur_dt.time() >= night_end_time:
                
                self.tonight_open_positions = self.get_open_NS_positions()
                if len(self.tonight_open_positions) > 0:
                    print(f'Night Ended @ {self.cur_dt.time()} Start Managing open positions: ')
                for position in self.tonight_open_positions:
                    if position.symbol not in self.sym_time_stopT: 
                        continue
                    if position.magic in self.sym_time_stopT[position.symbol]['Magics']:
                        t = Thread(target=self.manage_open_position, args=(position,))
                        t.start()
                        self.threads += [t]
                break
        
        # save report when all positions closed
        for t in self.threads:
            t.join()
        self.report_df.to_csv(self.report_fn, index=True)     
        print(f'Positions all closed, report has been saved at {self.report_fn}. Have a great day!')  


    @property
    def balance(self):
        # Get instant balance
        account_info = self.mt5.account_info() 
        if account_info!=None:
            return account_info.balance
        else:
            raise ValueError(f'Error retriving balance. Code {self.mt5.last_error()}')

    @property
    def cur_open_position_ids(self):
        try:
            return [pos.identifier for pos in self.mt5.positions_get()]
        except:
            print(mt5.last_error())
            return []

    @property
    def cur_dt(self):
        time = self.mt5.symbol_info_tick('EURUSD').time
        if time == None:
            print(self.mt5.last_error())
            return datetime.utcnow() + timedelta(hours=broker_gmt_shift)
        else:
            return epoch_to_dt(time)


    def get_open_NS_positions(self):
        '''
        get current open night scalper positions
        '''
        all_positions = self.mt5.positions_get()
        return [pos for pos in all_positions if pos.time >= self.start_time]


    def manage_open_position(self, position):
        '''
        Monitor/Proces open position until it gets closed.
        After it closed, update thhe report
        '''
        print('Managing open position: ')
        print(position)

        print()
        pid = position.identifier
        volume = position.volume if position.type == 0 else -position.volume
        self.report_df.loc[pid, 'symbol'] = position.symbol
        self.report_df.loc[pid, 'magic'] = position.magic
        self.report_df.loc[pid, 'comment'] = position.comment
        self.report_df.loc[pid, 'volume'] = volume
        self.report_df.loc[pid, 'en_time'] = epoch_to_dt(position.time)
        self.report_df.loc[pid, 'en_price'] = position.price_open

        _sim_closed = False
        while (pid in self.cur_open_position_ids):
            cond_to_close = self.cur_dt.time() >= self.sym_time_stopT[position.symbol]['StopT']
            if cond_to_close and not _sim_closed:
                if not TEST:
                    for num_tries in range(5):
                        success = self.close_position(position)
                        if success:
                            break
                        else:
                            print(f'Closing Failed {num_tries+1} times, Try again!')
                            sleep(1)
                    break

                # update position
                print(f'TEST MODE: Position should close now: {self.cur_dt}  {position} with Profit {position.profit}')
                position = self.mt5.positions_get()[self.cur_open_position_ids.index(pid)]
                self.report_df.loc[pid, 'profit_if'] = position.profit
                self.report_df.loc[pid, 'ex_time_if'] = self.cur_dt
                tick = self.mt5.symbol_info_tick(position.symbol)
                self.report_df.loc[pid, 'ex_price_if'] = tick.bid if volume > 0 else tick.ask
                _sim_closed = True
        
        # After closed, record 
        print(f'Position : {pid} is closed!')
        for num_tries in range(5):
            deals = self.mt5.history_deals_get(position=pid)
            if deals != None:
                deal_in, deal_out = deals
                self.report_df.loc[pid, 'ex_time'] = epoch_to_dt(deal_out.time)
                self.report_df.loc[pid, 'ex_price'] = deal_out.price
                self.report_df.loc[pid, 'profit'] = deal_out.profit
                break
            else:
                print(f'Get hist position Failed {num_tries+1} times, with Error {self.mt5.last_error()}, Try again!')
                sleep(1)

        
    def close_position(self, position):
        assert not TEST
        request={ 
            "action": self.mt5.TRADE_ACTION_DEAL, 
            "symbol": position.symbol, 
            "volume": position.volume, 
            "type": self.mt5.ORDER_TYPE_SELL if position.type==0 else self.mt5.ORDER_TYPE_BUY, 
            "position": position.identifier, 
            "magic": position.magic, 
            "comment": "Time Trigger", 
            "type_time": self.mt5.ORDER_TIME_GTC, 
            "type_filling": self.mt5.ORDER_FILLING_IOC, 
        } 
        # send a trading request 
        result=self.mt5.order_send(request)
        
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            print("  order_send failed, retcode={}".format(result.retcode)) 
            print("   result",result) 
            return False
        else:
            self.trigger_closed_positions += [position]
            return True



if __name__ == '__main__':
    print(f'Night Scalper Guard Started. Use Control+C to stop it.')
    while True:
        tonight = Tonight(mt5)
        print(f'Tonight Ends.')





