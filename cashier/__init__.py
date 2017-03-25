import os
import errno
import sqlite3
from time import time
from cPickle import loads, dumps
try:
    from thread import get_ident
except ImportError:
    from dummy_thread import get_ident
import cPickle as pickle
from hashlib import md5


class Cashier(object):
    _create_sql = 'CREATE TABLE IF NOT EXISTS bucket (key TEXT PRIMARY KEY, val BLOB, exp FLOAT)'
    _get_sql = 'SELECT val, exp FROM bucket WHERE key = ?'
    _del_sql = 'DELETE FROM bucket WHERE key = ?'
    _set_sql = 'INSERT OR REPLACE INTO bucket (key, val, exp) VALUES (?, ?, ?)'
    _count_sql = 'SELECT COUNT(*) FROM bucket'
    _oldest = 'select key FROM bucket ORDER BY exp ASC LIMIT 1'

    def __init__(self, file_name=".cache", default_timeout=84600, default_length=10000):
        """
        Inspired by: flask.pocoo.org/snippets/87/
        initialize Cashier object for handling SQLite
        :param file_name: SQLite file name - defaults to .cache
        :param default_timeout: expiry for the stored params -> value - Default: 84600
        :param default_length: max length of the cache - oldest gets popped once full - Default length: 10,000
        """
        self.path = os.path.abspath(file_name)
        try:
            open(self.path, 'ab')
        except OSError, e:
            if e.errno != errno.EEXIST or not os.path.isfile(self.path):
                raise
        self.default_timeout = default_timeout
        self.default_length = default_length
        self.connection_cache = {}

    def clear(self):
        """
        Clear cache
        """
        os.unlink(self.path)

    def _get_conn(self, key):
        key = dumps(key, 0)
        t_id = get_ident()
        if t_id not in self.connection_cache:
            self.connection_cache[t_id] = {}
        if key not in self.connection_cache[t_id]:
            conn = sqlite3.Connection(self.path, timeout=60)
            with conn:
                conn.execute(self._create_sql)
            self.connection_cache[t_id][key] = conn
        return self.connection_cache[t_id][key]

    def get(self, key):
        """
        get value for a key
        removes a key if expired
        """
        rv = None
        with self._get_conn(key) as conn:
            for row in conn.execute(self._get_sql, (key,)):
                expire = row[1]
                if expire > time():
                    rv = loads(str(row[0]))
                    break
                if expire <= time():
                    self.delete(key)
                    break
        return rv

    def delete(self, key):
        """
        delete a key from the cache file
        """
        with self._get_conn(key) as conn:
            conn.execute(self._del_sql, (key,))

    def set(self, key, value):
        """
        set new key value to the cache
        If cache default length reached,
        will remove the oldest one and write the new one
        """
        value = buffer(dumps(value, 2))
        with self._get_conn(key) as conn:
            if conn.execute(self._count_sql).next() >= (self.default_length,):
                old_key = conn.execute(self._oldest).next()
                if old_key:
                    self.delete(old_key[0])
            conn.execute(self._set_sql, (key, value, time() + self.default_timeout))


def cache(cache_file=".cache", cache_time=84600, cache_length=10000, retry_if_blank=False):
    """
    Cache function results into a SQLite locally. Extremely handy when you are dealing with I/O heavy operations
    which seldom changes or CPU intensive functions as well.
    :param cache_file: SQLite3 file name to which cached data should be written into
        defaults to .cache
    :param cache_time: how long should the data be cached
        defaults to 1 day
    :param cache_length: how many different arguments and corresponding data should be cached
        defaults to 10000
    :param retry_if_blank: If True, will retry for the data if blank data is cached
    :return:
    """
    def decorator(fn):
        def wrapped(*args, **kwargs):
            md5_key = md5(str(args)).hexdigest()
            c = Cashier(cache_file, cache_time, cache_length)
            datum = c.get(md5_key)
            if datum:
                info = pickle.loads(datum)
                if not retry_if_blank:
                    return info
                elif info:
                    return info
            res = fn(*args, **kwargs)
            c.set(md5_key, pickle.dumps(res))
            return res
        return wrapped
    return decorator
