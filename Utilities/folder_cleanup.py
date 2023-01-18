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
import shutil
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

def recursivermdir(rootloc):
    try:
        sublocs=os.listdir(rootloc)
    except Exception as e:
        print(e)
        return
    if len(sublocs)>0:
        for subloc in sublocs:
            if(os.path.isdir(rootloc+"/"+subloc)):
                recursivermdir(rootloc+"/"+subloc)

    

    try:
        print(".hdds" in rootloc)
        if(".hdds" in rootloc):
            print("Removing ",rootloc)
            shutil.rmtree(rootloc)
        else:
            print("Removing ",rootloc)
            os.rmdir(rootloc)
    except Exception as e:
        print(e)
        pass


locations=["REQUESTEDMC_OUTPUT","REQUESTEDMC_LOGS"]
for location in locations:
    outdir_root="/osgpool/halld/mcwrap/"+location+"/"

    alldirs=os.listdir(outdir_root)

    for dirs in alldirs:
        query='SELECT Completed_Time,Notified FROM Project where OutputLocation LIKE "%'+dirs+'%"'
        #print(query)
        dbcursor.execute(query)
        Project = dbcursor.fetchall()
        #print(Project)
        if(len(Project)==0):
            #print("no project")
            recursivermdir(outdir_root+"/"+dirs)
        elif(len(Project)==1):
            #print("Project Found")
            if(str(Project[0]["Notified"])=="1" and str(Project[0]["Notified"]) !="" ):
                recursivermdir(outdir_root+"/"+dirs)
        else:
            #print("HOW?!?!?!")
            print(outdir_root+"/"+dirs)
            if(dirs=="dalton" or dirs=="pippimeta_flat_NoDelta_2018-08_20191006081957pm" ):
                recursivermdir(outdir_root+"/"+dirs)