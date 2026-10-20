import time
import baostock as bs
from multiprocessing import Process, Queue

def w(wid, codes, q):
    time.sleep(wid * 1.5)
    bs.login()
    t0 = time.time()
    count = 0
    for c in codes:
        rs = bs.query_history_k_data_plus(c, 'date,close', start_date='2024-01-02', end_date='2024-01-15', frequency='d')
        if rs.data:
            count += len(rs.data)
    bs.logout()
    q.put((wid, time.time() - t0, count))

if __name__ == '__main__':
    q = Queue()
    p1 = Process(target=w, args=(0, ['sh.600000', 'sh.600004', 'sh.600006'], q))
    p2 = Process(target=w, args=(1, ['sh.600007', 'sh.600008', 'sh.600009'], q))
    p1.start()
    p2.start()
    p1.join()
    p2.join()
    while not q.empty():
        print('Result:', q.get())
