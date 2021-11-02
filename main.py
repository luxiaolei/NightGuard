import logging
from nightguard import MT5Api, Tonight

def run():
    mt5api = MT5Api()
    pq_in, q_out = mt5api.get_timmer_Qs()

    while True:
        tonight = Tonight(mt5api)
        tonight.arrange_tonight_tasks(pq_in)
        pq_in.put((
            tonight.tonight_end_dt, {'task': Tonight.END}
        ))
        logging.info(f'All tasks arranged, will end tonight at {tonight.tonight_end_dt}. Waiting for first task...')

        while True:
            _, task = q_out.get()
            task_name = task['task']
            logging.debug(f'Get a task {task}')
            if task_name == Tonight.CLOSE_POSITION:
                tonight.close_position(task['symbol'], task['magics'])
            elif task_name == Tonight.END:
                tonight.close()
                break
            


        
if __name__ == '__main__':
    run()