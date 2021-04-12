#!/usr/bin/env python3
##########################################################################################################################
#
# 2017/03 Thomas Britton
#
#   Options:
#      MC variation can be changed by supplying "variation=xxxxx" option otherwise default: mc
#      the number of events to be generated per file (except for any remainder) can be set by "per_file=xxxx" default: 1000
#
#      If the user does not want genr8, geant, smearing, reconstruction to be performed the sequence will be terminated at the first instance of genr8=0,geant=0,mcsmear=0,recon=0 default: all on
#      Similarly, if the user wishes to retain the files created by any step you can supply the cleangenr8=0, cleangeant=0, cleanmcsmear=0, or cleanrecon=0 options.  By default all but the reconstruction files #      are cleaned. 
#
#      The reconstruction step is multi-threaded, for this step, if enabled, the script will use 4 threads.  This threading can be changed with the "numthreads=xxx" option 
#
#      By default the job will run interactively in the local directory.  If the user wishes to submit the jobs to swif the option "swif=1" must be supplied.
#
# SWIF DOCUMENTATION:
# https://scicomp.jlab.org/docs/swif
# https://scicomp.jlab.org/docs/swif-cli
# https://scicomp.jlab.org/help/swif/add-job.txt #consider phase!
#
##########################################################################################################################
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

def main(argv):

    queryosgjobs="SELECT ID,BatchJobID from Attempts where NumStarts is NULL && BatchSystem=\"OSG\" ORDER by ID asc;"# || (Status='4' && ExitCode != 0 && ProgramFailed is NULL) ORDER BY ID desc;"
    #print queryosgjobs
    dbcursor.execute(queryosgjobs)
    Alljobs = dbcursor.fetchall()

    print(len(Alljobs))

    for job in Alljobs:
        
        historystatuscommand="condor_history -limit 1 "+str(job["BatchJobID"])+" -json"
        print(historystatuscommand)
        jsonOutputstr=subprocess.check_output(historystatuscommand.split(" "))
        #historystatuscommand_exitcode ="condor_history -limit 1 "+str(job["BatchJobID"])+" -json | grep Exit"
        #exitCode_out=subprocess.check_output(historystatuscommand_exitcode.split(" "))
               
        print("================")
        print(jsonOutputstr)
        print("================")
        
        if( str(jsonOutputstr, "utf-8") != ""):
            JSON_jobar=json.loads(str(jsonOutputstr, "utf-8"))
            #print JSON_jobar[0]

            if JSON_jobar == []:
                updatejobstatus="UPDATE Attempts SET NumStarts=-1"
                updatejobstatus=updatejobstatus+" WHERE BatchJobID='"+str(job["BatchJobID"])+"';"

                print(updatejobstatus)
                dbcursor.execute(updatejobstatus)
                dbcnx.commit()
                continue

            JSON_job=JSON_jobar[0]
                    
            #print("Num starts:",JSON_job["NumJobStarts"])
            NumStarts=str(JSON_job["NumJobStarts"])

            updatejobstatus="UPDATE Attempts SET NumStarts="+str(NumStarts)
            updatejobstatus=updatejobstatus+" WHERE BatchJobID='"+str(job["BatchJobID"])+"';"

            print(updatejobstatus)
        else:
            updatejobstatus="UPDATE Attempts SET NumStarts=-1"
            updatejobstatus=updatejobstatus+" WHERE BatchJobID='"+str(job["BatchJobID"])+"';"

            print(updatejobstatus)


if __name__ == "__main__":
   main(sys.argv[1:])
