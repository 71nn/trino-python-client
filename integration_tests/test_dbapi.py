# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, division, print_function
from datetime import datetime
import uuid
import math

import fixtures
from fixtures import run_presto
import pytest
import pytz

import trino
from trino.exceptions import PrestoQueryError
from trino.transaction import IsolationLevel


@pytest.fixture
def presto_connection(run_presto):
    _, host, port = run_presto

    yield trino.dbapi.Connection(
        host=host, port=port, user="test", source="test", max_attempts=1
    )


@pytest.fixture
def presto_connection_with_transaction(run_presto):
    _, host, port = run_presto

    yield trino.dbapi.Connection(
        host=host,
        port=port,
        user="test",
        source="test",
        max_attempts=1,
        isolation_level=IsolationLevel.READ_UNCOMMITTED,
    )


def test_select_query(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("select * from system.runtime.nodes")
    rows = cur.fetchall()
    assert len(rows) > 0
    row = rows[0]
    assert row[2] == fixtures.PRESTO_VERSION
    columns = dict([desc[:2] for desc in cur.description])
    assert columns["node_id"] == "varchar"
    assert columns["http_uri"] == "varchar"
    assert columns["node_version"] == "varchar"
    assert columns["coordinator"] == "boolean"
    assert columns["state"] == "varchar"


def test_select_query_result_iteration(presto_connection):
    cur0 = presto_connection.cursor()
    cur0.execute("select custkey from tpch.sf1.customer LIMIT 10")
    rows0 = cur0.genall()

    cur1 = presto_connection.cursor()
    cur1.execute("select custkey from tpch.sf1.customer LIMIT 10")
    rows1 = cur1.fetchall()

    assert len(list(rows0)) == len(rows1)


def test_select_query_result_iteration_statement_params(presto_connection):
    cur = presto_connection.cursor()
    cur.execute(
        """
        select * from (
            values
            (1, 'one', 'a'),
            (2, 'two', 'b'),
            (3, 'three', 'c'),
            (4, 'four', 'd'),
            (5, 'five', 'e')
        ) x (id, name, letter)
        where id >= ?
        """,
        params=(3,)  # expecting all the rows with id >= 3
    )


def test_none_query_param(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT ?", params=(None,))
    rows = cur.fetchall()

    assert rows[0][0] == None


def test_string_query_param(presto_connection):
    cur = presto_connection.cursor()

    cur.execute("SELECT ?", params=("six'",))
    rows = cur.fetchall()

    assert rows[0][0] == "six'"


def test_datetime_query_param(presto_connection):
    cur = presto_connection.cursor()

    cur.execute(
            "SELECT ?", 
            params=(datetime(2020, 1, 1, 0, 0, 0),)
            )
    rows = cur.fetchall()

    assert rows[0][0] == "2020-01-01 00:00:00.000"

    cur.execute(
            "SELECT ?", 
            params=(datetime(2020, 1, 1, 0, 0, 0, tzinfo=pytz.utc),)
            )
    rows = cur.fetchall()

    assert rows[0][0] == "2020-01-01 00:00:00.000 UTC"
    assert cur.description[0][1] == "timestamp with time zone"


def test_array_query_param(presto_connection):
    cur = presto_connection.cursor()

    cur.execute("SELECT ?", params=([1, 2, 3],))
    rows = cur.fetchall()

    assert rows[0][0] == [1, 2, 3]

    cur.execute(
            "SELECT ?", 
            params=([[1, 2, 3],[4,5,6]],))
    rows = cur.fetchall()

    assert rows[0][0] == [[1, 2, 3],[4,5,6]]

    cur.execute("SELECT TYPEOF(?)", params=([1, 2, 3],))
    rows = cur.fetchall()

    assert rows[0][0] == "array(integer)"


def test_dict_query_param(presto_connection):
    cur = presto_connection.cursor()

    cur.execute("SELECT ?", params=({"foo": "bar"},))
    rows = cur.fetchall()

    assert rows[0][0] == {"foo": "bar"}

    cur.execute("SELECT TYPEOF(?)", params=({"foo": "bar"},))
    rows = cur.fetchall()

    assert rows[0][0] == "map(varchar(3), varchar(3))"


def test_boolean_query_param(presto_connection):
    cur = presto_connection.cursor()

    cur.execute("SELECT ?", params=(True,))
    rows = cur.fetchall()

    assert rows[0][0] == True

    cur.execute("SELECT ?", params=(False,))
    rows = cur.fetchall()

    assert rows[0][0] == False


def test_float_query_param(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT ?", params=(1.1,))
    rows = cur.fetchall()

    assert cur.description[0][1] == "double"
    assert rows[0][0] == 1.1


@pytest.mark.skip(reason="Nan currently not returning the correct python type for nan")
def test_float_nan_query_param(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT ?", params=(float("nan"),))
    rows = cur.fetchall()

    assert cur.description[0][1] == "double"
    assert isinstance(rows[0][0], float)
    assert math.isnan(rows[0][0])


@pytest.mark.skip(reason="Nan currently not returning the correct python type fon inf")
def test_float_inf_query_param(presto_connection):
    cur.execute("SELECT ?", params=(float("inf"),))
    rows = cur.fetchall()

    assert rows[0][0] == float("inf")

    cur.execute("SELECT ?", params=(-float("-inf"),))
    rows = cur.fetchall()

    assert rows[0][0] == float("-inf")


def test_int_query_param(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT ?", params=(3,))
    rows = cur.fetchall()

    assert rows[0][0] == 3
    assert cur.description[0][1] == "integer"

    cur.execute("SELECT ?", params=(9223372036854775807,))
    rows = cur.fetchall()

    assert rows[0][0] == 9223372036854775807
    assert cur.description[0][1] == "bigint"


@pytest.mark.parametrize('params', [
    'NOT A LIST OR TUPPLE',
    {'invalid', 'params'},
    object,
])
def test_select_query_invalid_params(presto_connection, params):
    cur = presto_connection.cursor()
    with pytest.raises(AssertionError):
        cur.execute('select ?', params=params)


def test_select_cursor_iteration(presto_connection):
    cur0 = presto_connection.cursor()
    cur0.execute("select nationkey from tpch.sf1.nation")
    rows0 = []
    for row in cur0:
        rows0.append(row)

    cur1 = presto_connection.cursor()
    cur1.execute("select nationkey from tpch.sf1.nation")
    rows1 = cur1.fetchall()

    assert len(rows0) == len(rows1)
    assert sorted(rows0) == sorted(rows1)


def test_select_query_no_result(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("select * from system.runtime.nodes where false")
    rows = cur.fetchall()
    assert len(rows) == 0


def test_select_query_stats(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")

    query_id = cur.stats["queryId"]
    completed_splits = cur.stats["completedSplits"]
    cpu_time_millis = cur.stats["cpuTimeMillis"]
    processed_bytes = cur.stats["processedBytes"]
    processed_rows = cur.stats["processedRows"]
    wall_time_millis = cur.stats["wallTimeMillis"]

    while cur.fetchone() is not None:
        assert query_id == cur.stats["queryId"]
        assert completed_splits <= cur.stats["completedSplits"]
        assert cpu_time_millis <= cur.stats["cpuTimeMillis"]
        assert processed_bytes <= cur.stats["processedBytes"]
        assert processed_rows <= cur.stats["processedRows"]
        assert wall_time_millis <= cur.stats["wallTimeMillis"]

        query_id = cur.stats["queryId"]
        completed_splits = cur.stats["completedSplits"]
        cpu_time_millis = cur.stats["cpuTimeMillis"]
        processed_bytes = cur.stats["processedBytes"]
        processed_rows = cur.stats["processedRows"]
        wall_time_millis = cur.stats["wallTimeMillis"]


def test_select_failed_query(presto_connection):
    cur = presto_connection.cursor()
    with pytest.raises(trino.exceptions.PrestoUserError):
        cur.execute("select * from catalog.schema.do_not_exist")
        cur.fetchall()


def test_select_tpch_1000(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
    rows = cur.fetchall()
    assert len(rows) == 1000


def test_cancel_query(presto_connection):
    cur = presto_connection.cursor()
    cur.execute("select * from tpch.sf1.customer")
    cur.fetchone()  # TODO (https://github.com/prestosql/presto/issues/2683) test with and without .fetchone
    cur.cancel()  # would raise an exception if cancel fails

    cur = presto_connection.cursor()
    with pytest.raises(Exception) as cancel_error:
        cur.cancel()
    assert "Cancel query failed; no running query" in str(cancel_error.value)


def test_session_properties(run_presto):
    _, host, port = run_presto

    connection = trino.dbapi.Connection(
        host=host,
        port=port,
        user="test",
        source="test",
        session_properties={"query_max_run_time": "10m", "query_priority": "1"},
        max_attempts=1,
    )
    cur = connection.cursor()
    cur.execute("SHOW SESSION")
    rows = cur.fetchall()
    assert len(rows) > 2
    for prop, value, _, _, _ in rows:
        if prop == "query_max_run_time":
            assert value == "10m"
        elif prop == "query_priority":
            assert value == "1"


def test_transaction_single(presto_connection_with_transaction):
    connection = presto_connection_with_transaction
    for _ in range(3):
        cur = connection.cursor()
        cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows = cur.fetchall()
        connection.commit()
        assert len(rows) == 1000


def test_transaction_rollback(presto_connection_with_transaction):
    connection = presto_connection_with_transaction
    for _ in range(3):
        cur = connection.cursor()
        cur.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows = cur.fetchall()
        connection.rollback()
        assert len(rows) == 1000


def test_transaction_multiple(presto_connection_with_transaction):
    with presto_connection_with_transaction as connection:
        cur1 = connection.cursor()
        cur1.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows1 = cur1.fetchall()

        cur2 = connection.cursor()
        cur2.execute("SELECT * FROM tpch.sf1.customer LIMIT 1000")
        rows2 = cur2.fetchall()

    assert len(rows1) == 1000
    assert len(rows2) == 1000

def test_invalid_query_throws_correct_error(presto_connection):
    """
    tests that an invalid query raises the correct exception
    """
    cur = presto_connection.cursor()
    with pytest.raises(PrestoQueryError):
        cur.execute(
            """
            select * FRMO foo WHERE x = ?; 
            """,
            params=(3,),
        )
