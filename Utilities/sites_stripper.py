import MySQLdb
#import MySQLdb.cursors
from os import environ
from optparse import OptionParser
import os.path
#import mysql.connector
import time
import os
import getpass
import sys
import re
import subprocess
from subprocess import call
import socket
import glob
import json
import time
from datetime import timedelta
from datetime import datetime
import smtplib
from email.message import EmailMessage
from multiprocessing import Process
import random
import pipes
import random
import shutil

dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

try:
        dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
except:
        print("WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE CONTROLLED OR MONITORED")
        pass

HeldJobs_q="SELECT BatchJobID from Attempts where Status=5 && ID>40000 && SubmitHost=\"scosg20.jlab.org\" order by ID asc"
dbcursor.execute(HeldJobs_q)
heldJobs=dbcursor.fetchall()


unique_entry_list=[]
for j in heldJobs:
    print(j['BatchJobID'])
    statuscommand="condor_q "+str(j["BatchJobID"])+" -json | grep MATCH_GLIDEIN_Entry_Name"
    #print("Checking status:",statuscommand)
    Outputstr=subprocess.check_output(statuscommand.split(" "))
    entry_name=Outputstr.split(":")[-1].strip()[:-1]
    if entry_name not in unique_entry_list:
        unique_entry_list.append(entry_name)
        
print("Unique entries:",unique_entry_list)
