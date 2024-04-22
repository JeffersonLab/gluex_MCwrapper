#!/usr/bin/env python3
import MySQLdb
import sys
import datetime
import os.path
from optparse import OptionParser
import subprocess
from subprocess import call
from subprocess import Popen, PIPE
import socket
import pprint
import math
import numpy as np

dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbname = 'gluex_mc'



conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
curs=conn.cursor(MySQLdb.cursors.DictCursor)

def main(argv):
    print("begin")
    year = int(argv[0])

    projcount_q="SELECT COUNT(*) from Project where Submit_Time>'2022-01-01' and Submit_Time<'2023-01-01';"

    numevts_q="SELECT SUM(NumEvents) from Project where Submit_Time>'2023-01-01' and Submit_Time<'2024-01-01';"

    active_jobs_q="SELECT Count(*) from Jobs inner join Project on Jobs.Project_ID=Project.ID where Submit_Time>'2023-01-01' and Submit_Time<'2024-01-01' and Jobs.IsActive=1;"

    total_cputime_q="SELECT Sum(CPUTime) from Attempts inner join Jobs on Jobs.ID=Attempts.Job_ID inner join Project on Project.ID=Jobs.Project_ID where Project.Submit_Time>'2018-01-01' and Project.Submit_Time<'2019-01-01';"

    unique_users_q="SELECT DISTINCT UName from Project where Submit_Time>'2022-01-01' and Submit_Time<'2023-01-01';"

    avg_attempt_count_for_active_q="SELECT AVG(attempt_count) AS average_attempt_count FROM (SELECT COUNT(*) AS attempt_count FROM Attempts INNER JOIN Jobs ON Jobs.ID = Attempts.Job_ID INNER JOIN Project ON Project.ID = Jobs.Project_ID WHERE Jobs.IsActive = 1 AND Project.Submit_Time > '2018-01-01' AND Project.Submit_Time < '2019-01-01' GROUP BY Jobs.ID) AS attempt_counts;"

if __name__ == "__main__":
    main(sys.argv[1:])