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
def CheckForFile(rootLoc,expFile):
    found=False
    subloc="hddm"
    if(expFile.split(".")[1]=="root"):
        subloc="root/monitoring_hists"

    if(os.path.isfile('/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT/'+rootLoc+"/"+subloc+"/"+expFile) or os.path.isfile('/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) or os.path.isfile('/mss/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) ):
        found=True
    else:
        print(rootLoc+"/"+subloc+"/"+expFile)
    return found

def checkProjectsForCompletion():
    OutstandingProjectsQuery="SELECT * FROM Project WHERE (Is_Dispatched != '0' && Tested != '-1' && Tested != '2' ) && Notified is NULL"
    dbcursor.execute(OutstandingProjectsQuery)
    OutstandingProjects=dbcursor.fetchall()

    outdir_root="/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT/"

    for proj in OutstandingProjects:
        print(proj['ID'])
        locparts=proj['OutputLocation'].split("/")

        print("~~~~~~~~~~~~~~~~~~")
        files=[]
        dirs=[]
        #print locparts[len(locparts)-2]
        for r, dirs, files in os.walk(outdir_root+locparts[len(locparts)-2]) : 
            files = [f for f in files if not f[0] == '.']
            dirs[:] = [d for d in dirs if not d[0] == '.']

        print(len(files))
        print(dirs)

        filesToMove = len(files) #sum([len(files) for r, d, files in os.walk(outdir_root+locparts[len(locparts)-2])])
        #print cpt
        #print(proj)
        
        print(filesToMove)
        #DISTINCT ID ------in query below
        TOTCompletedQuery ="SELECT * From Jobs WHERE Project_ID="+str(proj['ID'])+" && IsActive=1 && ID in (SELECT DISTINCT Job_ID FROM Attempts WHERE ExitCode = 0 && (Status ='4' || Status='succeeded')  && ExitCode IS NOT NULL);" 
        dbcursor.execute(TOTCompletedQuery)
        fulfilledJobs=dbcursor.fetchall()
        #print(fulfilledJobs)

        
        if(proj["Tested"]==2 or proj["Tested"]==3):
            continue

        rootLoc=proj['OutputLocation'].split("REQUESTED_MC")[1].replace("/","")
        nullify_list=[]
        for job in fulfilledJobs:
            STANDARD_NAME=str(job['RunNumber']).zfill(6)+'_'+str(job['FileNumber']).zfill(3)
            if(proj['Generator']!="file:"):
                STANDARD_NAME=proj['Generator']+'_'+STANDARD_NAME
            #print(STANDARD_NAME)

            Expected_returned_files=[]

            if(str(proj['RunGeneration'])=="1" and str(proj['SaveGeneration'])=="1"):
                Expected_returned_files.append(STANDARD_NAME+".hddm")
            if(str(proj['RunGeant'])=="1" and str(proj['SaveGeant'])=="1"):
                Expected_returned_files.append(STANDARD_NAME+'_geant'+proj['GeantVersion']+'.hddm')
            if(str(proj['RunSmear'])=="1" and str(proj['SaveSmear'])=="1"):
                Expected_returned_files.append(STANDARD_NAME+'_geant'+proj['GeantVersion']+'_smeared.hddm')
            if(str(proj['RunReconstruction'])=="1" and str(proj['SaveReconstruction'])=="1"):
                Expected_returned_files.append('dana_rest_'+STANDARD_NAME+'.hddm')
                Expected_returned_files.append('hd_root_'+STANDARD_NAME+'.root')

            found_AllexpFile=True
            for expFile in Expected_returned_files:
                #print(expFile)
                found=CheckForFile(rootLoc,expFile)
                if not found:
                    found_AllexpFile=False
                    break
            
            if not found_AllexpFile:
                print("FLAG LAST ATTEMPT AS SPECIAL FAIL 404")
                GET_Attempt_to_update="SELECT * FROM Attempts WHERE Job_ID="+str(job["ID"])+" ORDER BY ID DESC;"
                dbcursor.execute(GET_Attempt_to_update)
                Attempt_to_update=dbcursor.fetchall()[0]
                print(Attempt_to_update)
                Update_q="UPDATE Attempts Set ExitCode=404 where ID="+str(Attempt_to_update["ID"])
                dbcursor.execute(Update_q)
                dbcnx.commit()
                nullify_list.append(job["ID"]) 
                
            
        #if len(nullify_list) != 0:
        #    for null in nullify_list:
        #        index=0
        #        for job in fulfilledJobs:
        #            if(job["ID"] == null):
        #                print(null)
        #                print(job["ID"])
        #                fulfilledJobs.pop(index)
        #                break
        #            index=index+1
                    
        TOTJobs="SELECT ID From Jobs WHERE Project_ID="+str(proj['ID'])+" && IsActive=1;"
        dbcursor.execute(TOTJobs)
        AllActiveJobs=dbcursor.fetchall()
        print("=====================")
        print(proj['ID'])
        print(proj['OutputLocation'])
        print(len(fulfilledJobs)-len(nullify_list))
        print(len(AllActiveJobs))
        print("TO MOVE: "+str(filesToMove))

        totalSubmitted="SELECT SUM(NumEvts) from Jobs where Project_ID="+str(proj['ID'])
        dbcursor.execute(totalSubmitted)
        submitted_evtNum=dbcursor.fetchall()
        print(submitted_evtNum[0]["SUM(NumEvts)"])
        print(proj["NumEvents"]-len(AllActiveJobs))

        if(len(fulfilledJobs)-len(nullify_list)==len(AllActiveJobs) and len(AllActiveJobs) != 0 and filesToMove ==0 and submitted_evtNum[0]["SUM(NumEvts)"] >= proj["NumEvents"]):#-len(AllActiveJobs)):
            print("DONE")

            getFinalCompleteTime="SELECT MAX(Completed_Time) FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID="+str(proj['ID'])+");"
            print(getFinalCompleteTime)
            dbcursor.execute(getFinalCompleteTime)
            finalTimeRes=dbcursor.fetchall()
            #print "============"
            #print finalTimeRes[0]["MAX(Completed_Time)"]
            updateProjectstatus="UPDATE Project SET Completed_Time="+"'"+str(finalTimeRes[0]["MAX(Completed_Time)"])+"'"+ " WHERE ID="+str(proj['ID'])+";"
            print(updateProjectstatus)
            #print "============"
            dbcursor.execute(updateProjectstatus)
            dbcnx.commit()

            #print "echo 'Your Project ID "+str(proj['ID'])+" has been completed.  Output may be found:\n"+proj['OutputLocation']+"' | mail -s 'GlueX MC Request #"+str(proj['ID'])+" Completed' "+str(proj['Email'])
            msg = EmailMessage()
            msg.set_content('Your Project ID '+str(proj['ID'])+' has been completed.  Output may be found here:\n'+str(proj['OutputLocation']))

            # me == the sender's email address                                                                                                                                                                                 
            # you == the recipient's email address                                                                                                                                                                             
            msg['Subject'] = 'GlueX MC Request #'+str(proj['ID'])+' Completed'
            msg['From'] = 'MCwrapper-bot'
            msg['To'] = str(proj['Email'])

            # Send the message via our own SMTP server.                                                                                                                                                                        
            s = smtplib.SMTP('localhost')
            s.send_message(msg)
            s.quit()
            #subprocess.call("echo 'Your Project ID "+str(proj['ID'])+" has been completed.  Output may be found here:\n"+proj['OutputLocation']+"' | mail -s 'GlueX MC Request #"+str(proj['ID'], "utf-8")+" Completed' "+str(proj['Email'], "utf-8"),shell=True)
            sql_notified = "UPDATE Project Set Notified=1 WHERE ID="+str(proj['ID'])
            dbcursor.execute(sql_notified)
            dbcnx.commit()
        else:
            #print("ELSE")
            #print(proj['ID'])
            updateProjectstatus="UPDATE Project SET Completed_Time=NULL WHERE ID="+str(proj['ID'])+";"
            #print(updateProjectstatus)
            dbcursor.execute(updateProjectstatus)
            dbcnx.commit()


def checkSWIF(WKflows_to_check):
        #print "CHECKING SWIF JOBS"
        #queryswifjobs="SELECT OutputLocation,ID,NumEvents,Completed_Time FROM Project WHERE ID IN (SELECT Project_ID FROM Jobs WHERE IsActive=1 && ID IN (SELECT Job_ID FROM Attempts WHERE BatchSystem= 'SWIF') )"
        dbcnxSWIF=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursorSWIF=dbcnxSWIF.cursor(MySQLdb.cursors.DictCursor)
        
        AllWkFlows=WKflows_to_check
        #LOOP OVER SWIF WORKFLOWS
        #print "================================="
        #print AllWkFlows
        projIDs=[]
        for workflow in AllWkFlows:
            splitnames=workflow["OutputLocation"].split("/")
            wkflowname=splitnames[len(splitnames)-2]
            #print wkflowname
            ProjID=workflow["ID"]
            projIDs.append(ProjID)
            #statuscommand="swif status -workflow "+str("pim_g3_1_70_v2_20180718011203pm")+" -jobs -display json"
            statuscommand="/site/bin/swif status -workflow proj"+str(ProjID)+"_"+str(wkflowname)+" -jobs -display json"
            print(statuscommand)
            jsonOutputstr=subprocess.check_output(statuscommand.split(" "))
            ReturnedJobs=json.loads(str(jsonOutputstr, "utf-8"))
            #print "*******************"
            #print ReturnedJobs
            #print "======================"
            #LOOP OVER ALL JOBS IN WORKFLOW
            for job in ReturnedJobs["jobs"]:
                check_query="SELECT Job_ID,Status,ExitCode from Attempts WHERE BatchJobID="+str(job["id"])
                dbcursor.execute(check_query)
                recordedJobStatus = dbcursor.fetchall()
                print(recordedJobStatus)
                if( (recordedJobStatus[0]["Status"]=="succeeded" and recordedJobStatus[0]["ExitCode"]==0) or recordedJobStatus[0]["Status"]==6 ):
                    print("continuing")
                    continue
                #NON RUNNING DISPATCHED JOBS ARE A SPECIAL CASE
                if int(job["num_attempts"]) == 0:
                    #print "truncated update of attempt pre dispatch"
                    updatejobstatus="UPDATE Attempts SET Status=\""+str(job["status"])+"\"" +" WHERE BatchJobID="+str(job["id"])
                    print(updatejobstatus)
                    dbcursorSWIF.execute(updatejobstatus)
                    dbcnxSWIF.commit()
                else:
                    #print "Update all the attempts"
                    LoggedSWIFAttemps_query="SELECT ID from Attempts where BatchJobID="+str(job["id"])+" ORDER BY ID"
                    dbcursorSWIF.execute(LoggedSWIFAttemps_query)
                    LoggedSWIFAttemps=dbcursorSWIF.fetchall()
                    loggedindex=0
                    #LOOP OVER ALL ATTEMPTS OF A JOBS
                    for attempt in job["attempts"]:
                        #print "|||||||||||||||||||||"
    
                        WallTime=timedelta(seconds=0)
                        CpuTime=timedelta(seconds=0)
                        Start_Time=datetime.fromtimestamp(float(0.0)/float(1000))
                        RAMUsed="0"
                        ExitCode=0
                        #print(attempt)
                        #print("||||||||||||||||||||")
                        #print(attempt["exitcode"])
                        #if not attempt["exitcode"]:
                        #    continue
                        #print("EXIT CODE")
                        #print('exitcode' in attempt)
                        #print(job["status"])
                        if "exitcode" in attempt or job["status"]=="succeeded":
                            if "exitcode" in attempt:
                                ExitCode=attempt["exitcode"]
                        else:
                            ExitCode=-1
                        
                        if(job["status"]=="succeeded"):
                            print("SUCCESS")

                       # print("exit code done")
                        Completed_Time='NULL'

                        if(job["status"]=="problem" or job["status"]=="succeeded") and "auger_ts_complete" in attempt:
                            Completed_Time=attempt["auger_ts_complete"]
                            #print datetime.fromtimestamp(float(attempt["auger_ts_complete"])/float(1000))
                        #print("TIMES")
                        #print(attempt["auger_wall_sec"])
                        if("auger_wall_sec" in attempt):
                            WallTime=timedelta(seconds=attempt["auger_wall_sec"])
                        if("auger_ts_active" in attempt):
                            Start_Time=datetime.fromtimestamp(float(attempt["auger_ts_active"])/float(1000))
                            
                        if("auger_cpu_sec" in attempt):
                            CpuTime=timedelta(seconds=attempt["auger_cpu_sec"])
                        if "auger_vmem_kb" in attempt:
                            RAMUsed=str(float(attempt["auger_vmem_kb"])/1000.)

                        #print RAMUsed
                        #print("|||||||||||||||||||||")
                        #SOME VODOO IF RETRY JOBS HAPPENED OUTSIDE OF THE DB
                        if loggedindex == len(LoggedSWIFAttemps):
                            print("FOUND AN ATTEMPT EXTERNALLY CREATED")
                            GetLinkToJob_query="SELECT Job_ID FROM Attempts WHERE BatchJobID="+str(job["id"])
                            #print GetLinkToJob_query
                            dbcursorSWIF.execute(GetLinkToJob_query)
                            LinkToJob=dbcursorSWIF.fetchall()

                            if(len(LinkToJob)==0):
                                continue

                            #print len(LoggedSWIFAttemps)
                            #print LinkToJob
                            submitTime=0.0
                            #print attempt["auger_ts_submitted"]
                            if "auger_ts_submitted" in attempt:
                                submitTime=float(attempt["auger_ts_submitted"])
                            
                            #print datetime.fromtimestamp(submitTime/float(1000))
                            
                            addFoundAttempt="INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,BatchJobID, ThreadsRequested, RAMRequested,Start_Time) VALUES (%s,'%s','SWIF',%s,%s,%s,'%s')" % (LinkToJob[0]["Job_ID"],datetime.fromtimestamp(submitTime/float(1000)),attempt["job_id"],attempt["cpu_cores"], "'"+str(float(attempt["ram_bytes"])/float(1000000000))+"GB"+"'",Start_Time)
                            #print addFoundAttempt
                            dbcursorSWIF.execute(addFoundAttempt)
                            dbcnxSWIF.commit()

                            LoggedSWIFAttemps_query="SELECT ID from Attempts where BatchJobID="+str(job["id"])+" ORDER BY ID"
                            dbcursorSWIF.execute(LoggedSWIFAttemps_query)
                            LoggedSWIFAttemps=dbcursorSWIF.fetchall()
                            #print len(LoggedSWIFAttemps)

                        #print "UPDATING ATTEMPT"
                        #print (attempt["auger_ts_complete"])
                        if not "auger_ts_complete" in attempt:
                            Completed_Time='NULL'

                        if not "exitcode" in attempt:
                            ExitCode='NULL'
                        #print str(ExitCode)
                        #UPDATE THE SATUS
                        #print Completed_Time
                        if str(ExitCode) == "232" or str(ExitCode) == "1000":
                            print("EXIT CODE 232 DETECTED")
                            getrunNum="SELECT RunNumber, Project_ID from Jobs where ID="+str(recordedJobStatus[0]["Job_ID"])
                            dbcursorSWIF.execute(getrunNum)
                            thisJOB = dbcursorSWIF.fetchall()
                            #print(len(thisJOB))
                            if len(thisJOB) == 1:
                                thisJOB_RunNumber=thisJOB[0]["RunNumber"]
                                getBKG="SELECT BKG from Project where ID="+str(thisJOB[0]["Project_ID"])
                                dbcursorSWIF.execute(getBKG)
                                thisJOB_BKG = dbcursorSWIF.fetchall()
                                #print(len(thisJOB_BKG))
                                if len(thisJOB_BKG) == 1:
                                    print(thisJOB_BKG)
                                    attempt_BKG=thisJOB_BKG[0]["BKG"]
                                    #print(attempt_BKG)
                                    #print("SPLITTING")
                                    attempt_BKG_parts=attempt_BKG.split(":")
                                    print(len(attempt_BKG_parts))
                                    if len(attempt_BKG_parts) != 1:
                                        locally_found=os.path.isfile("/osgpool/halld/random_triggers/"+str(attempt_BKG_parts[1])+"/run"+str(thisJOB_RunNumber).zfill(6)+"_random.hddm")
                                        if locally_found:
                                            print("found file locally: "+str("/osgpool/halld/random_triggers/"+str(attempt_BKG_parts[1])+"/run"+str(thisJOB_RunNumber).zfill(6)+"_random.hddm"))

                                            if(locally_found):
                                                JOB_STATUS="problem"
                                                ExitCode=-232

                                        else:
                                            print("6 job stat")
                                            JOB_STATUS=6
                                            deactivate_Job="UPDATE Jobs set IsActive=0 where ID="+str(recordedJobStatus[0]["Job_ID"])+";"
                                            dbcursorSWIF.execute(deactivate_Job)
                                            dbcnxSWIF.commit()

                        running_location='NULL'
                        if "auger_node" in attempt:
                            running_location=attempt["auger_node"]

                        updatejobstatus="UPDATE Attempts SET Status=\""+str(job["status"])+"\", ExitCode="+str(ExitCode)+", RunningLocation="+"'"+str(running_location)+"'"+", WallTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(WallTime.seconds))+"'"+", Start_Time="+"'"+str(Start_Time)+"'"+", CPUTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(CpuTime.seconds))+"'"+", RAMUsed="+"'"+RAMUsed+"'"+" WHERE BatchJobID="+str(job["id"])+" && ID="+str(LoggedSWIFAttemps[loggedindex]["ID"])
                        if Completed_Time != 'NULL':
                                #print "COMPLETED_TIME"
                                updatejobstatus="UPDATE Attempts SET Status=\""+str(job["status"])+"\", ExitCode="+str(ExitCode)+", Completed_Time='"+str(datetime.fromtimestamp(float(attempt["auger_ts_complete"])/float(1000)))+"'"+", RunningLocation="+"'"+str(running_location)+"'"+", WallTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(WallTime.seconds))+"'"+", Start_Time="+"'"+str(Start_Time)+"'"+", CPUTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(CpuTime.seconds))+"'"+", RAMUsed="+"'"+RAMUsed+"'"+" WHERE BatchJobID="+str(job["id"])+" && ID="+str(LoggedSWIFAttemps[loggedindex]["ID"])
                       

                        dbcursorSWIF.execute(updatejobstatus)
                        dbcnxSWIF.commit()
                        loggedindex+=1


def UpdateOutputSize():
    getUntotaled="SELECT ID FROM Project WHERE Completed_Time IS NULL && Is_Dispatched != '0';"
    #print querygetLoc
    dbcursor.execute(getUntotaled)
    Projects = dbcursor.fetchall()

    for pr in Projects:
        id=pr["ID"]
        #print "Updating size for: "+str(id)
        querygetLoc="SELECT * FROM Project WHERE ID="+str(id)+";"
        #print querygetLoc
        dbcursor.execute(querygetLoc)
        Project = dbcursor.fetchall()
        location=Project[0]["OutputLocation"]

        if Project[0]["FinalDestination"]:
            location=Project[0]["FinalDestination"]

        try:
            statuscommand="du -sh --exclude \".*\" --total "+location
            print(statuscommand)
            totalSizeStr=subprocess.check_output([statuscommand], shell=True)
            #print "==============="
            #print totalSizeStr.split("\n")[1].split("total")[0]

            updateProjectSizeOut="UPDATE Project SET TotalSizeOut=\""+totalSizeStr.split("\n")[1].split("total")[0]+"\" WHERE ID="+str(id)
            dbcursor.execute(updateProjectSizeOut)
            dbcnx.commit()
        except:
            pass
        

def checkOSG(Jobs_List):
        dbcnxOSG=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursorOSG=dbcnxOSG.cursor(MySQLdb.cursors.DictCursor)
        Alljobs=Jobs_List
        count=0
        updateRate=.25
        #print("UPDATING "+str(len(Alljobs)))

        if ( len(Alljobs) == 0 ):
            return
            #print(str(os.getpid())+" SLEEP")
            #time.sleep(60)
        for job in Alljobs:
            #print job
            count+=1
            #print(str(os.getpid())+" condor_q")
            #print(count)
            modulo=int(len(Jobs_List)*updateRate)
            if modulo ==0:
                modulo=10
            if(count%(modulo)==0):
                print(str(os.getpid())+" : "+str(count))
            statuscommand="condor_q "+str(job["BatchJobID"])+" -json"
            #print(statuscommand)
            jsonOutputstr=subprocess.check_output(statuscommand.split(" "))
            #print "================"
            #print(jsonOutputstr)
            #print "================"
            if( str(jsonOutputstr, "utf-8") != ""):
                #print("JSONING")
                JSON_jobar=json.loads(str(jsonOutputstr, "utf-8"))
                #print(JSON_jobar[0])
                if JSON_jobar == []:
                    continue
                JSON_job=JSON_jobar[0]
                #print JSON_job
                ExitCode="NULL"
                #print(JSON_job["JobStatus"])
                if (JSON_job["JobStatus"]!=3 and "ExitCode" in JSON_job):
                    ExitCode=str(JSON_job["ExitCode"])
                    #print ExitCode

                if (JSON_job["JobStatus"] == 2):
                    ExitCode="NULL"
                    

                Completed_Time='NULL'

                if(JSON_job["JobStatus"] >= 3 and "JobFinishedHookDone" in JSON_job):
                    Completed_Time=JSON_job["JobFinishedHookDone"]

                WallTime=timedelta(seconds=JSON_job["RemoteWallClockTime"])
                CpuTime=timedelta(seconds=JSON_job["RemoteUserCpu"])
                Start_Time=0
                if "JobStartDate" in JSON_job:
                    Start_Time=JSON_job["JobStartDate"]
                #"MemoryUsage": "\/Expr(( ( ResidentSetSize + 1023 ) / 1024 ))\/"
                RAMUSED=str(float(JSON_job["ImageSize_RAW"])/ float(1024))
                TransINSize=JSON_job["TransferInputSizeMB"]

                REMOTE_HOST="NA"
                if "RemoteHost" in JSON_job :
                    REMOTE_HOST=str(JSON_job["RemoteHost"])

                JOB_STATUS=JSON_job["JobStatus"]
                HELDREASON=0

                if "HoldReasonCode" in JSON_job:
                    HELDREASON=JSON_job["HoldReasonCode"]

                if JOB_STATUS == 5:
                    missingF=True
                    for f in JSON_job["TransferInput"].split(","):
                        if "_random.hddm" in f:
                            print(f)
                            missingF=os.path.isfile(f)
                            print(missingF)
                    if missingF == False:
                        #print "set to 6"
                        JOB_STATUS=6
                        deactivate_Job="UPDATE Jobs set IsActive=0 where ID="+str(job["Job_ID"])+";"
                        dbcursorOSG.execute(deactivate_Job)
                        dbcnxOSG.commit()


                RunIP="NULL"
                if "LastPublicClaimId" in JSON_job:
                    ipstr=str(JSON_job["LastPublicClaimId"])
                    ipstr=ipstr.split("#")[0]
                    ipstr=ipstr[1:-1].split(":")[0]
                    RunIP=ipstr
                #print("UPDATE")
                updatejobstatus="UPDATE Attempts SET Status=\""+str(JOB_STATUS)+"\", ExitCode="+ExitCode+", Start_Time="+"'"+str(datetime.fromtimestamp(float(Start_Time)))+"'"+", RunningLocation="+"'"+str(REMOTE_HOST)+"'"+", WallTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(WallTime.seconds))+"'"+", CPUTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(CpuTime.seconds))+"'"+", RAMUsed="+"'"+RAMUSED+"'"+", Size_In="+str(TransINSize)+", RunIP='"+str(RunIP)+"' WHERE BatchJobID='"+str(job["BatchJobID"])+"';"
                if Completed_Time != 'NULL':
                    updatejobstatus="UPDATE Attempts SET Status=\""+str(JOB_STATUS)+"\", ExitCode="+ExitCode+", Completed_Time='"+str(datetime.fromtimestamp(float(Completed_Time)))+"'"+", Start_Time="+"'"+str(datetime.fromtimestamp(float(Start_Time)))+"'"+", RunningLocation="+"'"+str(REMOTE_HOST)+"'"+", WallTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(WallTime.seconds))+"'"+", CPUTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(CpuTime.seconds))+"'"+", RAMUsed="+"'"+RAMUSED+"'"+", Size_In="+str(TransINSize)+", RunIP='"+str(RunIP)+"' WHERE BatchJobID='"+str(job["BatchJobID"])+"';"


                #print updatejobstatus
                dbcursorOSG.execute(updatejobstatus)
                dbcnxOSG.commit()
            else:
                #print "looking up history"
                #print(str(os.getpid())+" condor_history")
                historystatuscommand="condor_history -limit 1 "+str(job["BatchJobID"])+" -json"
                print(historystatuscommand)
                jsonOutputstr=subprocess.check_output(historystatuscommand.split(" "))
                #print "================"
                #print(jsonOutputstr)
                #print "================"
                if( str(jsonOutputstr, "utf-8") != ""):
                    JSON_jobar=json.loads(str(jsonOutputstr, "utf-8"))
                    #print JSON_jobar[0]
                    if JSON_jobar == []:
                        continue
                    JSON_job=JSON_jobar[0]
                    
                    ExitCode="NULL"
                    if (JSON_job["JobStatus"]!=3 and "ExitCode" in JSON_job):
                        ExitCode=str(JSON_job["ExitCode"])
                    
                    Start_Time=0
                    if "JobStartDate" in JSON_job:
                        Start_Time=JSON_job["JobStartDate"]

                    Completed_Time='NULL'
                    if(JSON_job["JobStatus"] >= 3 and "JobFinishedHookDone" in JSON_job):
                        Completed_Time=JSON_job["JobFinishedHookDone"]

                    WallTime=timedelta(seconds=JSON_job["RemoteWallClockTime"])
                    CpuTime=timedelta(seconds=JSON_job["RemoteUserCpu"])
                    #"MemoryUsage": "\/Expr(( ( ResidentSetSize + 1023 ) / 1024 ))\/"
                    RAMUSED=str(float(JSON_job["ImageSize_RAW"])/ float(1024))
                    TransINSize=JSON_job["TransferInputSizeMB"]


                    JOB_STATUS=JSON_job["JobStatus"]
                    
                    HELDREASON=0

                    if "HoldReasonCode" in JSON_job:
                        HELDREASON=JSON_job["HoldReasonCode"]

                    if JOB_STATUS == 5:
                        missingF=False
                        for f in JSON_job["TransferInput"].split(","):
                            if ".hddm" in f:
                                missingF=os.path.isfile(f)
                        if missingF == False:
                            JOB_STATUS=6

                    if str(ExitCode) == "232" or str(ExitCode) == "1000":
                        print("EXIT CODE 232 DETECTED")
                        getrunNum="SELECT RunNumber, Project_ID from Jobs where ID="+str(job["Job_ID"])
                        dbcursorOSG.execute(getrunNum)
                        thisJOB = dbcursorOSG.fetchall()
                        #print(len(thisJOB))
                        if len(thisJOB) == 1:
                            thisJOB_RunNumber=thisJOB[0]["RunNumber"]
                            getBKG="SELECT BKG from Project where ID="+str(thisJOB[0]["Project_ID"])
                            dbcursorOSG.execute(getBKG)
                            thisJOB_BKG = dbcursorOSG.fetchall()
                            #print(len(thisJOB_BKG))
                            if len(thisJOB_BKG) == 1:
                                print(thisJOB_BKG)
                                attempt_BKG=thisJOB_BKG[0]["BKG"]
                                #print(attempt_BKG)
                                #print("SPLITTING")
                                attempt_BKG_parts=attempt_BKG.split(":")
                                print(len(attempt_BKG_parts))
                                if len(attempt_BKG_parts) != 1:
                                    locally_found=os.path.isfile("/osgpool/halld/random_triggers/"+str(attempt_BKG_parts[1])+"/run"+str(thisJOB_RunNumber).zfill(6)+"_random.hddm")
                                    if locally_found:
                                        print("found file locally: "+str("/osgpool/halld/random_triggers/"+str(attempt_BKG_parts[1])+"/run"+str(thisJOB_RunNumber).zfill(6)+"_random.hddm"))
                                        response=os.system("ping -c 1 nod25.phys.uconn.edu")
                                        print("PING RESPONSE:"+str(response))
                                        if response != 0:
                                            print("-1 job stat")
                                            JOB_STATUS=-1 #hold until host comes back
                                        else:
                                            print("7 job stat")
                                            JOB_STATUS=7 #globus needs doing?
                                            
                                            if(locally_found):
                                                JOB_STATUS=4
                                                ExitCode=-232

                                    else:
                                        print("6 job stat")
                                        JOB_STATUS=6
                                        deactivate_Job="UPDATE Jobs set IsActive=0 where ID="+str(job["Job_ID"])+";"
                                        dbcursorOSG.execute(deactivate_Job)
                                        dbcnxOSG.commit()
                    
                    failedProgram="NULL"
                    
                    if ( str(ExitCode) != "0" and str(ExitCode) != "NULL"):
                        #print("CRASHED")
                        std_out_loc=str(JSON_job["Out"])
                        if( not os.path.isfile(std_out_loc)):
                            std_out_loc="/cache/halld/gluex_simulations/REQUESTED_MC/"+std_out_loc.split("REQUESTEDMC_OUTPUT")[1]
                        #print(std_out_loc)
                        with open(std_out_loc) as stdoutF:
                            for num,line in enumerate(stdoutF,1):
                                if "Something went wrong with" in line:
                                    #print(line)
                                    splitl=line.strip().split(" ")
                                    #print(splitl[len(splitl)-1])
                                    failedProgram=splitl[len(splitl)-1]
                                    
                        
                    failedProgram=failedProgram.replace("(","\(")
                    failedProgram=failedProgram.replace(")","\)")    
                        

                    RunIP="NULL"
                    if "LastPublicClaimId" in JSON_job:
                        ipstr=str(JSON_job["LastPublicClaimId"])
                        ipstr=ipstr.split("#")[0]
                        ipstr=ipstr[1:-1].split(":")[0]
                        RunIP=ipstr

                    LastRemoteHost="NULL"
                    if "LastRemoteHost" in JSON_job:
                        LastRemoteHost=JSON_job["LastRemoteHost"]

                    
                    #print LastRemoteHost
                    updatejobstatus="UPDATE Attempts SET Status=\""+str(JOB_STATUS)+"\", ExitCode="+str(ExitCode)+", Start_Time="+"'"+str(datetime.fromtimestamp(float(Start_Time)))+"'"+", RunningLocation="+"'"+str(LastRemoteHost)+"'"+", WallTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(WallTime.seconds))+"'"+", CPUTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(CpuTime.seconds))+"'"+", RAMUsed="+"'"+RAMUSED+"'"+", Size_In="+str(TransINSize)+", RunIP='"+str(RunIP)+"'"
                    
                    if Completed_Time != 'NULL':
                        updatejobstatus="UPDATE Attempts SET Status=\""+str(JOB_STATUS)+"\", ExitCode="+str(ExitCode)+", Start_Time="+"'"+str(datetime.fromtimestamp(float(Start_Time)))+"'"+", Completed_Time='"+str(datetime.fromtimestamp(float(Completed_Time)))+"'"+", RunningLocation="+"'"+str(LastRemoteHost)+"'"+", WallTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(WallTime.seconds))+"'"+", CPUTime="+"'"+time.strftime("%H:%M:%S",time.gmtime(CpuTime.seconds))+"'"+", RAMUsed="+"'"+RAMUSED+"'"+", Size_In="+str(TransINSize)+", RunIP='"+str(RunIP)+"'"

                    if failedProgram != 'NULL':
                        updatejobstatus=updatejobstatus+", ProgramFailed='"+str(failedProgram)+"'"

                    updatejobstatus=updatejobstatus+" WHERE BatchJobID='"+str(job["BatchJobID"])+"';"
                    #print(updatejobstatus)
                    
                    dbcursorOSG.execute(updatejobstatus)
                    dbcnxOSG.commit()

        time.sleep(random.randint(1,5))
        print("FINISHED CHECKING OSG")


########################################################## MAIN ##########################################################
def array_split(lst,n):
    to_return=[]
    for i in range(0,n):
        to_return.append([])
    
    for count, ele in enumerate(lst):
        #print(ele)
        index=count%n
        #print(index)
        to_return[index].append(ele)

    #print(count)
    #print(len(to_return))

    return to_return

def main(argv):

        spawnNum=20
        numOverRide=False

        if(len(argv) !=0):
            numOverRide=True
        
        numprocesses_running=subprocess.check_output(["echo `ps all -u tbritton | grep MCOverlord.py | grep -v grep | wc -l`"], shell=True)

        print(int(numprocesses_running))
        if(int(numprocesses_running) <2 or numOverRide):
            while(1):
                dbcursor.execute("INSERT INTO MCOverlord (Host,StartTime,Status) VALUES ('"+str(socket.gethostname())+"', NOW(), 'Running' )")
                dbcnx.commit()
                queryoverlords="SELECT MAX(ID) FROM MCOverlord;"
                dbcursor.execute(queryoverlords)
                lastid = dbcursor.fetchall()
                #print lastid
                try:
                    queryosgjobs="SELECT * from Attempts WHERE BatchSystem='OSG' && Status !='4' && Status !='3' && Status!= '6' && Status != '5';"# || (Status='4' && ExitCode != 0 && ProgramFailed is NULL) ORDER BY ID desc;"
                    #print queryosgjobs
                    dbcursor.execute(queryosgjobs)
                    Alljobs = dbcursor.fetchall()
                    Monitoring_assignments=array_split(Alljobs,spawnNum)
                    spawns=[]
                    for i in range(0,spawnNum):
                        print("block "+str(i))
                        print(len(Monitoring_assignments[i]))
                        p=Process(target=checkOSG,args=(Monitoring_assignments[i],))
                        p.daemon = True
                        spawns.append(p)
                        
                        #p.join()
                        
                    for i in range(0,len(spawns)):
                        #print("join "+str(i))
                        spawns[i].start()
                        
                    #time.sleep(2)
                    for i in range(0,len(spawns)):
                        if spawns[i].is_alive():
                            #print("join "+str(i))
                            spawns[i].join()

                    if(numOverRide == False): #INSURE OVERRIDE NEVER CAUSES THE VODOO TO CAUSE A RACE CONDITION
                        print("CHECKING SWIF ON MAIN")
                        queryswifjobs="SELECT * FROM Project WHERE Notified IS NULL && ID IN (SELECT Project_ID FROM Jobs WHERE IsActive=1 && ID IN (SELECT DISTINCT Job_ID FROM Attempts WHERE BatchSystem= 'SWIF' && (Status!='succeeded' || Status is NULL)) )"
                        dbcursor.execute(queryswifjobs)
                        AllWkFlows = dbcursor.fetchall()
                        checkSWIF(AllWkFlows)
                        #SWIF CHECK MUST BE SINGLE THREADED FOR NOW DUE TO THE VODOO NOT BEING THREAD SAFE
                    
                    #print(AllWkFlows)
                    #SWIFMonitoring_assignments=array_split(AllWkFlows,1)
                    #spawns=[]
                    #for i in range(0,1):
                    #    print("swif block "+str(i))
                    #    #print(len(Monitoring_assignments[i]))
                    #    p=Process(target=checkSWIF,args=(SWIFMonitoring_assignments[i],))
                    #    p.daemon = True
                    #    spawns.append(p)
                    #    
                    #    #p.join()
                    #    
                    #for i in range(0,len(spawns)):
                    #    #print("join "+str(i))
                    #    spawns[i].start()
                    #    
                    ##time.sleep(2)
                    #for i in range(0,len(spawns)):
                    #    if spawns[i].is_alive():
                    #        #print("join "+str(i))
                    #        spawns[i].join()
                    
                    print("CHECKING GLOBALS ON MAIN")
                    #UpdateOutputSize()
                    checkProjectsForCompletion()
                    dbcursor.execute("UPDATE MCOverlord SET EndTime=NOW(), Status=\"Success\" where ID="+str(lastid[0]["MAX(ID)"]))
                    dbcnx.commit()
                except Exception as e:
                    print("exception")
                    print(e)
                    #dbcursor.execute("UPDATE MCOverlord SET Status=\"Fail\" where ID="+str(lastid[0]["MAX(ID)"]))
                    #dbcnx.commit()
                    break


        dbcnx.close()
              
if __name__ == "__main__":
   main(sys.argv[1:])
