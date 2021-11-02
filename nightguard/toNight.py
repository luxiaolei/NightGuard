from logging import log
import pandas as pd

from time import sleep
from datetime import datetime, time, timedelta

from . import logging, PAK_DIR
from .mt5Api import MT5Api

from configobj import ConfigObj
from pathlib import Path



symstop_fn = PAK_DIR / 'symbol_stopT.csv'

class Tonight: 

    # Task name identifiers
    CLOSE_POSITION = 'CLOSE_POSITION'
    END = 'END'

    name = 'ST'

    MAGIC_ALL = -3418239482

    def __init__(self, mt5api, config_path=PAK_DIR/'Config.ini'):
        self.mt5 = mt5api
        if isinstance(config_path, str): config_path = Path(config_path)
        nightConf = ConfigObj(config_path.as_posix())['NightSetting']

        # Calculate `tonight_date` which is the date AFTER Rollover time.
        cur_time = self.mt5.broker_time_local
        if cur_time.time() < time(nightConf.as_int('NS_END_HOUR'), nightConf.as_int('NS_END_MINUTE')):
            night_date = cur_time.date()
        else:
            night_date = cur_time.date() + timedelta(days=1)

        if night_date.weekday() == 5:
            logging.info(f'Weekend ahead, positions will be managed on monday.')
            self.tonight_date = night_date + timedelta(days=2)
        else:
            self.tonight_date = night_date

        ## `tonight_end_dt` is the end of night also is the start of next night
        #end_time = time(nightConf.as_int('NS_START_HOUR'), nightConf.as_int('NS_START_MINUTE'))
        self.tonight_end_dt = datetime.combine(self.tonight_date+timedelta(days=1), time(0,0,1))
        self.tonight_start_dt = datetime.combine(self.tonight_date-timedelta(days=1), time(23,0))
        
        raw_stop_df = pd.read_csv(symstop_fn.as_posix(), index_col=0)
        raw_stop_df.Magics.fillna(self.MAGIC_ALL, inplace=True)
        raw_stop_df['Magics'] = raw_stop_df['Magics'].apply(
            lambda ms: [int(float(m)) for m in str(ms).split(';')]
        ) 
        self.raw_stop_df = raw_stop_df

        self._mangaged_pids = []
        self._record = {}

    def arrange_tonight_tasks(self, pq_in):
        """Returns a list of task tuple that instruct a timmer queue to process

        A closeing task is defined by a tuple, where the first element is excute time, 
        the second is a dict contains at least a compulsary key `task` with value specifies the
        task name, and/or other key value pairs for args of the task. 

        Example: 
            (close_time, {task: close, symbol: EURUSD, magics: [2,3]}

        Args:
            pq_in (PiorityQueue): Queue to put into
        
        Returns:
            list: list of task tuple instruct the closing 
        """
        stop_df = self.raw_stop_df.copy()

        stop_df['StopT'] = pd.to_datetime(str(self.tonight_date) + ' ' + stop_df['StopT'])
        stop_df = stop_df[stop_df.Magics.apply(lambda ms:len(ms)) >= 1]
        stop_df = stop_df.sort_values('StopT')

        stop_df_print = stop_df.copy()
        stop_df_print['Magics to Stop'] = stop_df_print.Magics.apply(
            lambda m: 'ALL' if m==[self.MAGIC_ALL] else str(m)) 
        stop_df_print = stop_df_print[['StopT', 'Magics to Stop']]
        print(f'**** Tonight arrangement ****')
        print(f"{stop_df_print}")
        #print(f"{stop_df.to_markdown()}")

        sym_time_stopT = pd.read_csv(symstop_fn.as_posix(), index_col=0)
        sym_time_stopT['StopT'] = sym_time_stopT.StopT.apply(lambda t: pd.to_datetime(t).time())

        for i, (sym, row) in enumerate(stop_df.iterrows()):

            pq_in.put((
            row.StopT + timedelta(microseconds=i), {'task': self.CLOSE_POSITION, 'symbol': sym, 'magics': row.Magics}
            ))

    def close_position(self, symbol, magics):
        '''
        Monitor/Proces open position until it gets closed.
        After it closed, update thhe report

        '''
        cur_positions = self.mt5.cur_positions
        logging.debug(f'Trying to match cur_pos {cur_positions}')
        for pos in cur_positions:
            magic_match = (pos.magic in magics) or (magics[0] == self.MAGIC_ALL)
            time_con = pd.to_datetime(pos.time, unit='s') >= self.tonight_start_dt
            logging.debug(f'Position: {pos.symbol}, magic {pos.magic}')
            logging.debug(f'Magic match: {magic_match}, time con : {time_con}')
            if pos.symbol == symbol and magic_match and time_con:
                self._mangaged_pids += [pos.identifier]
                pos_str = f'Position {pos.symbol}  Magic {pos.magic} Current profit {pos.profit}'
                if self.mt5.TEST_MODE:
                    logging.info(f'TEST MODE Recording current profit as if we close it. {pos_str}')
                    volume = pos.volume if pos.type == 0 else -pos.volume
                    self._record[pos.identifier] = {
                        '-'.join([self.name, 'profit']): pos.profit,
                        '-'.join([self.name, 'Ex_Time']): self.mt5.broker_time,
                        '-'.join([self.name, 'Ex_Price']): self.mt5.get_price_to_close(pos),
                    }
                else:
                    logging.info(f'Closing position: {pos_str}')
                    self.mt5.close_position(pos, comment=self.name)
                    logging.info('Closed!')

    def close(self, report_fn_prefix=None):
        """
        Save reports of positions started from previous `night_end_dt` till `tonigh_end_dt`
        If TEST_MODE is on, also saves columns as if we close the positions.
        """
        start_dt = self.tonight_end_dt - timedelta(days=1)
        pos_hist = self.mt5.get_history_positions(start_dt, self.tonight_end_dt)
        pos_hist.to_csv('hist_pos.csv',index=True)
        # Filtout_magics
        logging.debug(f'Managed pids: {self._mangaged_pids}, pos_hist_pids: {pos_hist.index}')
        pos_hist = pos_hist[pos_hist.index.isin(self._mangaged_pids)]
        for pid, info in self._record.items():
            for k,v in info.items():
                pos_hist.loc[pid, k] = v
        
        logging.info('**** Tonight finished positions ****')
        print(pos_hist)

        if report_fn_prefix is None:
            report_fn = PAK_DIR / 'PositionReport.csv'
        else:
            report_fn = PAK_DIR / (report_fn_prefix + '_' + 'PositionReport.csv')

        if report_fn.exists():
            report_df = pd.read_csv(report_fn.as_posix(), index_col=0)
        else:
            report_df = pd.DataFrame()
        
        report_df = report_df.append(pos_hist)
        report_df.to_csv(report_fn.as_posix(), index=True)
        