#!/usr/bin/env python3
try:
    import rcdb
except Exception as e:
    print("IMPORT ERROR:",e)
    pass
from telnetlib import STATUS
import MySQLdb
import sys
import datetime
import os.path
import pwd
import time
import shlex
from optparse import OptionParser
try:
    import subprocess
    from subprocess import call
    from subprocess import Popen, PIPE
    import socket
    import pprint
    import smtplib                                                                                                                                                                          
    from email.message import EmailMessage
    from multiprocessing import Process, Queue
except Exception as e:
    print("ERROR:",e)
    pass


MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
MCWRAPPER_BOT_HOST_NAME=str(socket.gethostname())
dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

#get user name of current user
runner_name=pwd.getpwuid( os.getuid() )[0]

if( not (runner_name=="tbritton" or runner_name=="mcwrap")):
    print("ERROR: You must be tbritton or mcwrap to run this script")
    sys.exit(1)

conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
curs=conn.cursor(MySQLdb.cursors.DictCursor)

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

#DELETE FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID=65);

def RecallAll():
    #query="SELECT BatchJobID, BatchSystem from Attempts where (Status=\"2\" || Status=\"1\" || Status=\"5\") && SubmitHost=\""+MCWRAPPER_BOT_HOST_NAME+"\" && Job_ID in (SELECT ID from Jobs where Project_ID in (SELECT ID FROM Project where Tested=2 || Tested=4 || Tested=3 ));"
    query="SELECT a.BatchJobID, a.BatchSystem FROM Attempts a JOIN Jobs j ON a.Job_ID = j.ID JOIN Project p ON j.Project_ID = p.ID WHERE a.SubmitHost = \""+MCWRAPPER_BOT_HOST_NAME+"\" AND a.Status IN (\"1\", \"2\", \"5\") AND p.Tested IN (2, 3, 4);"
    print(query)
    curs.execute(query)
    rows=curs.fetchall()
    print("RECALLING "+str(len(rows)))
    i=0
    for row in rows:
        i=i+1
        print("RECALLING:",str(i),"/",str(len(rows)))
        if row["BatchSystem"] == "OSG":
            command="condor_rm "+str(row["BatchJobID"])
            cmd=Popen(command.split(" "),stdout=PIPE,stderr=PIPE)
            out, err = cmd.communicate()
            #print(out)
            #print(err)
            print(str(err,"utf-8"))
            if("not found" in str(err,"utf-8")):
                print("clear "+str(row["BatchJobID"]))
                updatequery="UPDATE Attempts SET Status=\"3\" where BatchJobID=\""+str(row["BatchJobID"])+"\""+" && SubmitHost=\""+MCWRAPPER_BOT_HOST_NAME+"\""
                print(updatequery)
                curs.execute(updatequery)
                conn.commit()
            if("Failed to end classad" in str(err,"utf-8")):
                break
            #subprocess.call(command,shell=True)

def BundleFiles(input,output):
    MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
    bundlecommand = "ssh ifarm1802 " + "echo hostname; source /group/halld/Software/build_scripts/gluex_env_jlab.csh; /usr/bin/python3.6 " + MCWRAPPER_BOT_HOME + "/Utilities/MCMerger.py -f " + input + "/ " + output + "/"
    print(bundlecommand)
    try:
        out = subprocess.check_output(shlex.split(bundlecommand), stderr=subprocess.STDOUT)
        return "SUCCESS"
    except subprocess.CalledProcessError as e:
        print(e.output)
        return "ERROR"

def DeclareAllComplete():
    conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
    curs=conn.cursor(MySQLdb.cursors.DictCursor)

    query="SELECT ID,OutputLocation,Email,Completed_Time from Project where Tested=4 && Notified is NULL;"
    curs.execute(query)
    rows=curs.fetchall()
    print("DECLARING",rows,"COMPLETE")
    
    for proj in rows:

        inputdir= proj["OutputLocation"].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/","/work/halld/gluex_simulations/REQUESTED_MC/")
        outputlocation="/".join(proj["OutputLocation"].split("/")[:-1])+"/"
        # outputlocation="/work/halld/gluex_simulations/MERGED_MC/"

        hours_to_wait=4

        #check if now is at least 4 hours later than the completion time
        if proj["Completed_Time"] is None:
            continue
        if datetime.datetime.now() < proj["Completed_Time"] + datetime.timedelta(hours=hours_to_wait):
            continue
        
        print("BundleFiles("+inputdir+","+outputlocation+")")
        mkdircommand="ssh ifarm1802 mkdir -p "+outputlocation
        print(mkdircommand)
        subprocess.call(mkdircommand.split(" "))
        #close the connection to the database while we run the bundle files
        conn.close()
        out=BundleFiles(inputdir,outputlocation)
        print("final output",out)

        if out == "ERROR":
            continue
        
        conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        curs=conn.cursor(MySQLdb.cursors.DictCursor)
        msg = EmailMessage()
        msg.set_content('Your Project ID '+str(proj['ID'])+' has been declared completed.  Outstanding jobs have been recalled. Output may be found here:\n'+proj['OutputLocation'])

        # me == the sender's email address                                                                                                                                                                                 
        # you == the recipient's email address                                                                                                                                                                             
        msg['Subject'] = 'GlueX MC Request #'+str(proj['ID'])+' Declared Completed'
        msg['From'] = 'MCwrapper-bot'
        msg['To'] = str(proj['Email'])

        # Send the message via our own SMTP server.                                                                                                                                                                        
        s = smtplib.SMTP('localhost')
        s.send_message(msg)
        s.quit()

        #subprocess.call("echo 'Your Project ID "+str(proj['ID'])+" has been declared completed.  Outstanding jobs have been recalled. Output may be found here:\n"+proj['OutputLocation']+"' | mail -s 'GlueX MC Request #"+str(proj['ID'])+" Completed' "+str(proj['Email']),shell=True)
        updatequery="UPDATE Project SET Notified=1 where ID="+str(proj["ID"]) #Completed_Time=NOW(),
        curs.execute(updatequery)
        conn.commit()

def CancelAll():
    query="SELECT ID,OutputLocation,Email from Project where Tested=3;"
    curs.execute(query)
    rows=curs.fetchall()
    for proj in rows:
        msg = EmailMessage()
        msg.set_content('Your Project ID '+str(proj['ID'])+' has been canceled.  Outstanding jobs have been recalled.')

        # me == the sender's email address                                                                                                                                                                                 
        # you == the recipient's email address                                                                                                                                                                             
        msg['Subject'] = 'GlueX MC Request #'+str(proj['ID'])+' Cancelled'
        msg['From'] = 'MCwrapper-bot'
        msg['To'] = str(proj['Email'])

        # Send the message via our own SMTP server.                                                                                                                                                                        
        s = smtplib.SMTP('localhost')
        s.send_message(msg)
        s.quit()

        #subprocess.call("echo 'Your Project ID "+str(proj['ID'])+" has been canceled.  Outstanding jobs have been recalled."+"' | mail -s 'GlueX MC Request #"+str(proj['ID'])+" Canceled' "+str(proj['Email']),shell=True)
        sql = "DELETE FROM Attempts where Job_ID in ( SELECT ID FROM Jobs WHERE Project_ID="+str(proj['ID'])+" );"

        sql2 = "DELETE FROM Jobs WHERE Project_ID="+str(proj['ID'])+";"
        sql3 = "UPDATE Project SET Is_Dispatched='0',Completed_Time=NULL,Dispatched_Time=NULL WHERE ID="+str(proj['ID']) 

        curs.execute(sql)
        curs.execute(sql2)
        curs.execute(sql3)
        
        delq= "DELETE FROM Project where ID="+str(proj['ID'])+";"
        curs.execute(delq)
        conn.commit()


def AutoLaunch():
    #print "in autolaunch"
    print("RECALLING...")
    RecallAll()
    print("CANCELING...")
    CancelAll()
    print("DECLARING...")
    DeclareAllComplete()

    #get the return from df -h | grep /osgpool/halld
    print("GETTING DF...")
    d_usage=str(subprocess.check_output("df -h | grep /osgpool/halld",shell=True),"utf-8").strip()
    print(d_usage)
    percent=int(d_usage.split(" ")[-2].split("%")[0])
    print("disk is",percent,"% full")
    if percent > 75:
        print("disk is too full, not launching")
        return
    


    print("RETRYING...")
    RetryAllJobs()
    print("TESTING...")
    query = "SELECT ID,Email,VersionSet,Tested,UName FROM Project WHERE (Tested = 0) && Dispatched_Time is NULL ORDER BY (SELECT Priority from Users where name=UName) DESC LIMIT 10;"
    print(query)
    curs.execute(query) 
    rows=curs.fetchall()
    #print rows
    print("TESTING: ",rows)

    print("Testing: ",len(rows))
    if len(rows) == 0:
        return
    spawns=[]
    results_array=[]
    for row in rows:
        results_array.append([])
    results_q = Queue()
    results_q.put(results_array)
    for i in range(0,len(rows)):
        if(rows[i]['Tested']!=0):
            continue
        print("Test process "+str(i))
        #print(len(Monitoring_assignments[i]))
        p=Process(target=ParallelTestProject,args=(results_q,i,rows[i],rows[i]['ID'],str(rows[i]["VersionSet"]),))
        spawns.append(p)
        time.sleep(1)

    for i in range(0,len(spawns)):
        time.sleep(5)
        spawns[i].start()
    
    for i in range(0,len(spawns)):
        if spawns[i].is_alive():
            #print("join "+str(i))            
            spawns[i].join(15*60)




def ListUnDispatched():
    query = "SELECT * FROM Project WHERE Is_Dispatched='0' || Is_Dispatched='0.0'"
    curs.execute(query) 
    rows=curs.fetchall()
    print(rows)

def DispatchProject(ID,SYSTEM,PERCENT):
    query = "SELECT * FROM Project WHERE ID="+str(ID)
    curs.execute(query) 
    rows=curs.fetchall()

    if(len(rows) != 0):
        if SYSTEM == "INTERACTIVE":
            DispatchToInteractive(ID,rows[0],PERCENT)
        elif SYSTEM == "SWIF":
            DispatchToSWIF(ID,rows[0],PERCENT)
        elif SYSTEM == "OSG":
            DispatchToOSG(ID,rows[0],PERCENT)
    else:
        print("Error: Cannot find Project with ID="+ID)
    
def RetryAllJobs(rlim=False):
    query= "SELECT ID,Notified FROM Project where Completed_Time is NULL && Is_Dispatched=1.0 && Tested!=2 && Tested!=4 && Tested!=-4 && Tested!=3;"
    print(query)
    curs.execute(query) 
    rows=curs.fetchall()
    for row in rows:
        if(row["Notified"] != 1):
            print("Retrying Project "+str(row["ID"]))
            if 1: #row["ID"] != 2509 and row["ID"] != 2510:
                RetryJobsFromProject(row["ID"],not rlim)
            else:
                continue
        else:
            print("Attempting to clean up Completed_Time")
            getFinalCompleteTime="SELECT MAX(Completed_Time) FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID="+str(row['ID'])+");"
            print(getFinalCompleteTime)
            curs.execute(getFinalCompleteTime)
            finalTimeRes=curs.fetchall()
            #print "============"
            print("Final Time", finalTimeRes[0]["MAX(Completed_Time)"])
            updateProjectstatus="UPDATE Project SET Completed_Time="+"'"+str(finalTimeRes[0]["MAX(Completed_Time)"])+"'"+ " WHERE ID="+str(row['ID'])+";"
            print(updateProjectstatus)
            #print "============"
            curs.execute(updateProjectstatus)
            conn.commit()

def RemoveAllJobs():
    query= "SELECT * FROM Attempts WHERE ID IN (SELECT Max(ID) FROM Attempts GROUP BY Job_ID) && SubmitHost=\""+MCWRAPPER_BOT_HOST_NAME+"\" && Job_ID IN (SELECT ID FROM Jobs WHERE IsActive=1 && Project_ID="+str(ID)+");"
    curs.execute(query) 
    rows=curs.fetchall()
    i=0
    for row in rows:
        if(row["BatchSystem"]=="OSG"):
            print(row["BatchJobID"])


def RetryJobsFromProject(ID, countLim):
    AllOSG=True
    #query= "SELECT * FROM Attempts WHERE ID IN (SELECT Max(ID) FROM Attempts WHERE SubmitHost=\""+MCWRAPPER_BOT_HOST_NAME+"\" GROUP BY Job_ID) && Job_ID IN (SELECT ID FROM Jobs WHERE IsActive=1 && Project_ID="+str(ID)+");"
    #query= "SELECT * FROM Attempts WHERE ID IN (SELECT Max(ID) FROM Attempts WHERE SubmitHost is not NULL GROUP BY Job_ID) && Job_ID IN (SELECT ID FROM Jobs WHERE IsActive=1 && Project_ID="+str(ID)+");"
    query="select Attempts.* from Jobs inner join Attempts on Attempts.Job_ID = Jobs.id and Attempts.id = (select max(id) from Attempts latest_attempts where latest_attempts.job_id = Jobs.id) where Project_ID = " +str(ID)
    curs.execute(query) 
    rows=curs.fetchall()
   
    projq="SELECT Tested from Project where ID="+str(ID)
    curs.execute(projq)
    proj=curs.fetchall()[0]
    i=0
    j=0
    k=0
    SWIF_retry_IDs=[]
    print(len(rows),"Jobs to retry")
    for row in rows:
        print("Project",ID,"   ",k+1,"/",len(rows),":",row["Job_ID"],":",row["BatchSystem"])
        if (row["BatchSystem"]=="SWIF"):
            if((row["Status"] == "succeeded" and row["ExitCode"] != 0) or (row["Status"]=="problem" and row["ExitCode"]!="232") or (proj['Tested']==1 and row["Status"]=="canceled" ) or (proj['Tested']==1 and row["Status"]=="failed" )):
            #if(row["Status"] != "succeeded"):
                print("Retrying SWIF job: ",row["Job_ID"])
                limiterq="SELECT COUNT(*) from Attempts where BatchJobID="+str(row["BatchJobID"])
                curs.execute(limiterq) 
                attres=curs.fetchall()[0]
                print(attres)
                if(attres["COUNT(*)"] < 15):
                    SWIF_retry_IDs.append(row["BatchJobID"])
                    #RetryJob(row["Job_ID"])
                    i=i+1
                if(AllOSG):
                    RetryJob(row["Job_ID"],AllOSG)
                
        elif (row["BatchSystem"]=="OSG"):
            #print "=========================="
            #print row
            #print row["Status"]
            #print row["ExitCode"]
            #print "=========================="
            if (row["Status"] == "4" and row["ExitCode"] != 0) or row["Status"] == "3" or row["Status"]=="5" or row["Status"]=="-1":
                print("Retrying OSG job: ",row["Job_ID"])
                if ( countLim ):
                    countq="SELECT Count(Job_ID) from Attempts where Job_ID="+str(row["Job_ID"])
                    curs.execute(countq)
                    count=curs.fetchall()
                    if int(count[0]["Count(Job_ID)"]) > 15 :
                        j=j+1
                        print("Job above count limit")
                        continue
                    
                    if row["Status"] == "-1":
                        #update Status and retry
                        statusUpdate="Update Attempts Set Status=\"4\" WHERE ID ="+str(row["ID"])
                        curs.execute(statusUpdate)
                        conn.commit()
                            
                RetryJob(row["Job_ID"],AllOSG)
                i=i+1
        k=k+1
    
    print(SWIF_retry_IDs)
    if(len(SWIF_retry_IDs)!=0 and AllOSG == False):
        queryproj = "SELECT * FROM Project WHERE ID="+str(ID)
        curs.execute(queryproj) 
        proj=curs.fetchall()
        splitL=len(proj[0]["OutputLocation"].split("/"))
        retry_swif_command="swif retry-jobs -workflow "+"proj"+str(ID)+"_"+proj[0]["OutputLocation"].split("/")[splitL-2]+" "+" ".join(SWIF_retry_IDs)
        print(retry_swif_command)
        status = subprocess.call(retry_swif_command, shell=True)
    
    
    print("retried "+str(i)+" Jobs")
    print(str(j)+" jobs over restart limit of 15")

#def DoMissingJobs(ID,SYS):
#    query="SELECT ID FROM Jobs where ID NOT IN (SELECT Job_ID FROM Attempts) && IsActive=1 && Project_ID="+str(ID)+";"
#    curs.execute(query) 
#    rows=curs.fetchall()
    #GET PROJECT INFO
    
#    for row in rows:
#        if(SYS == "OSG"):
        #TREAT LIKE NEW PROJECT WITH JUST THE JOB

def RetryJob(ID,AllOSG=False):
    
    #query= "SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts,Jobs WHERE Attempts.Job_ID = "+str(ID)
    query= "SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts WHERE Attempts.Job_ID = "+str(ID)
    #print(query)
    curs.execute(query) 
    rows=curs.fetchall()

    queryjob = "SELECT * FROM Jobs WHERE ID="+str(ID)
    curs.execute(queryjob) 
    job=curs.fetchall()

    queryproj = "SELECT * FROM Project WHERE ID IN (SELECT Project_ID FROM Jobs WHERE ID="+str(ID)+")"
    curs.execute(queryproj) 
    proj=curs.fetchall()

    cleangen=1
    if proj[0]["SaveGeneration"]==1:
        cleangen=0

    cleangeant=1
    if proj[0]["SaveGeant"]==1:
        cleangeant=0
    
    cleansmear=1
    if proj[0]["SaveSmear"]==1:
        cleansmear=0
    
    cleanrecon=1
    if proj[0]["SaveReconstruction"]==1:
        cleanrecon=0

    print("AllOSG? "+str(AllOSG))
    if(rows[0]["BatchSystem"] == "SWIF" and AllOSG==False):
        splitL=len(proj[0]["OutputLocation"].split("/"))
        command = "swif retry-jobs -workflow "+"proj"+str(proj[0]["ID"])+"_"+proj[0]["OutputLocation"].split("/")[splitL-2]+" "+rows[0]["BatchJobID"]
        #proj548_gen_amp_L1520_errval_20190522055719am
        print(command)
        status = subprocess.call(command, shell=True)
    elif(rows[0]["BatchSystem"] == "OSG" or AllOSG):
        #print "OSG JOB FOUND"
        status = subprocess.call("cp "+MCWRAPPER_BOT_HOME+"/examples/OSGShell.config ./MCDispatched_"+str(ID)+".config", shell=True)
        WritePayloadConfig(proj[0],"True",ID)
        per_file_num=20000
        get_perfile_q="SELECT PerFile from Generator_perfiles where GenName=\""+str(proj[0]["Generator"])+"\";"
        curs.execute(get_perfile_q) 
        genrow=curs.fetchall()
        try:
            per_file_num=genrow[0]["PerFile"]
        except Exception as e:
            print(e)
            pass
        command=MCWRAPPER_BOT_HOME+"/gluex_MC.py MCDispatched_"+str(ID)+".config "+str(job[0]["RunNumber"])+" "+str(job[0]["NumEvts"])+" per_file="+str(per_file_num)+"  base_file_number="+str(job[0]["FileNumber"])+" generate="+str(proj[0]["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(proj[0]["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(proj[0]["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(proj[0]["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid=-"+str(ID)+" batch=1 tobundle=0"
        print(command)
        status = subprocess.call(command, shell=True)

def CancelJob(ID):
    #deactivate
    query = "UPDATE Jobs SET IsActive=0 WHERE ID="+str(ID)
    curs.execute(query)
    conn.commit()

    #modify Is_Dispatched
    queryprojID="SELECT Project_ID FROM Jobs WHERE ID="+str(ID)
    curs.execute(queryprojID) 
    projID=curs.fetchall()

    queryproj = "SELECT SUM(NumEvts) FROM Jobs WHERE IsActive=1 && Project_ID="+str(projID[0]["Project_ID"])
    curs.execute(queryproj) 
    proj=curs.fetchall()

    queryproj2 = "SELECT NumEvents FROM Project WHERE ID="+str(projID[0]["Project_ID"])
    curs.execute(queryproj2) 
    projNumevt=curs.fetchall()

    totalActiveEvt=0
    #print proj[0]["SUM(NumEvts)"]
    if(str(proj[0]["SUM(NumEvts)"]) != "None"):
        totalActiveEvt=proj[0]["SUM(NumEvts)"]

    totalEvt=1
    #print projNumevt[0]["NumEvents"]
    if(projNumevt[0]["NumEvents"] != 'None'):
        totalEvt=projNumevt[0]["NumEvents"]

    newPrecent=float(totalActiveEvt)/float(totalEvt)

    updatequery="UPDATE Project SET Is_Dispatched='"+str(newPrecent)+"' WHERE ID="+str(projID[0]["Project_ID"])
    curs.execute(updatequery)
    conn.commit()

def CheckGenConfig(order):
    ID=order["ID"]
    print("checking/getting the generator config for project:",str(ID))
    fileSTR=order["Generator_Config"].strip()
    file_split=fileSTR.split("/")
    name=file_split[len(file_split)-1]
    #print name
    #print(fileSTR)
    #print("looking for generator config:",fileSTR)
    #print("os.path.isfile("+fileSTR+")")
    #print("is file:",os.path.isfile(fileSTR))
    copyTo="/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"
    running_hostname=socket.gethostname()
    if(os.path.isfile(fileSTR)==False and (running_hostname == "scosg16.jlab.org" or running_hostname == "scosg20.jlab.org" or running_hostname=="scosg2201.jlab.org") ):
        print("File not found and on submit node, attempting to copy to "+copyTo)
        #copyTo="/osgpool/halld/tbritton/REQUESTEDMC_CONFIGS/"
        copy_loc="ifarm1801-ib"
        if(running_hostname=="scosg2201.jlab.org"):
            copy_loc="ifarm1801"
        print("scp "+runner_name+"@"+copy_loc+":"+fileSTR.lstrip()+" "+copyTo+str(ID)+"_"+name)
        subprocess.call("scp "+runner_name+"@"+copy_loc+":"+fileSTR.lstrip()+" "+copyTo+str(ID)+"_"+name,shell=True)
        #subprocess.call("rsync -ruvt ifarm1402:"+fileSTR+" "+copyTo,shell=True)
        print("Updating order gen config:",fileSTR,"------>",copyTo+str(ID)+"_"+name)
        order["Generator_Config"]=copyTo+str(ID)+"_"+name
        print("returning",copyTo+str(ID)+"_"+name)
        return copyTo+str(ID)+"_"+name
    elif(os.path.isfile(fileSTR)==True and (running_hostname == "scosg16.jlab.org" or running_hostname == "scosg20.jlab.org" or running_hostname=="scosg2201.jlab.org") ):
        print("File found and on submit node")
        #copyTo="/osgpool/halld/tbritton/REQUESTEDMC_CONFIGS/"
        #print("scp tbritton@ifarm1801-ib:"+fileSTR+" "+copyTo+str(ID)+"_"+name)
        #subprocess.call("scp tbritton@ifarm1801-ib:"+fileSTR+" "+copyTo+str(ID)+"_"+name,shell=True)
        print("scp "+fileSTR+" "+copyTo+str(ID)+"_"+name)
        subprocess.call("scp "+fileSTR+" "+copyTo+str(ID)+"_"+name,shell=True)
        
        order["Generator_Config"]=copyTo+str(ID)+"_"+name #copyTo+name
        return copyTo+str(ID)+"_"+name
    elif os.path.isfile(fileSTR)==False and (running_hostname != "scosg16.jlab.org" or running_hostname != "scosg20.jlab.org" or running_hostname!="scosg2201.jlab.org"):
        print("File not found and not on submit node ")
        return copyTo+str(ID)+"_"+name

    return "True"

def source(script, update=True):
    """                                                                                                                                                                                                            
    http://pythonwise.blogspot.fr/2010/04/sourcing-shell-script.html (Miki Tebeka)                                                                                                                                 
    http://stackoverflow.com/questions/3503719/#comment28061110_3505826 (ahal)                                                                                                                                     
    """
    import subprocess
    import os
    proc = subprocess.Popen(
        ['bash', '-c', 'set -a && source {} && env -0'.format(script)],
        stdout=subprocess.PIPE, shell=False)
    output, err = proc.communicate()
    output = output.decode('utf8')
    env = dict((line.split("=", 1) for line in output.split('\x00') if line))
    if update:
        os.environ.update(env)
    return env


def ParallelTestProject(results_q,index,row,ID,versionSet,commands_to_call=""):
    skip_Test=False

    mktestdir="mkdir -p TestProj_"+str(ID)
    subprocess.call(mktestdir,shell=True)
    os.chdir("./TestProj_"+str(ID))
    subprocess.call("rm -f MCDispatched_"+str(ID)+".config", shell=True)
    print("TESTING PROJECT "+str(ID))
    query = "SELECT * FROM Project WHERE ID="+str(ID)
    print(str(index)+":  "+query)
    curs.execute(query) 
    rows=curs.fetchall()
    order=rows[0]

    origOutLoc=order["OutputLocation"]
    orig_dirname=origOutLoc.split("/")[-2]
    new_dirname="_".join(orig_dirname.split("_")[:-1])+"_"+str(ID)
    new_full_dirname=origOutLoc.replace(orig_dirname,new_dirname)


    print("order", order)
    print("========================")
    print(order["Generator_Config"])
    newLoc=CheckGenConfig(order)
    print(order["Generator_Config"])
    print("========================")
    print(newLoc)
    if(newLoc!="True"):
        curs.execute(query) 
        rows=curs.fetchall()
        order=rows[0]

    already_passed_q="SELECT COUNT(*) from Jobs where Project_ID="+str(ID)
    curs.execute(already_passed_q)
    already_passed=curs.fetchall()

    if(already_passed[0]["COUNT(*)"]>0):
        updatequery="UPDATE Project SET Tested=1, OutputLocation=\""+new_full_dirname+"\" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()
        STATUS="Success"
        return STATUS

    output="Dispatch_Failure"
    errors="Dispatch_Failure"
    STATUS=-1
    if(order["RunNumHigh"] != order["RunNumLow"] and order["Generator"]=="file:"):
        updatequery="UPDATE Project SET Tested=-1"+" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()

        print(bcolors.FAIL+"TEST FAILED"+bcolors.ENDC)
        print("rm -rf "+order["OutputLocation"])

        return ["oh no!!!",-1,"MCwrapper cannot currently handle an input file with many run numbers properly"]

    if(not order["VersionSet"]):
        skip_Test=True
        output="oh no!!!"
        errors="Somehow a versionSet was not selected.  Please edit the submission via the link to select a version set."


    if(not skip_Test):
        WritePayloadConfig(order,newLoc)
        RunNumber=str(order["RunNumLow"])

        print(str(index)+":  "+"Wrote Payload")
        print("original RCDB QUERY:", order["RCDBQuery"])
        query_to_do=order["RCDBQuery"]
        if(order["RunNumLow"] != order["RunNumHigh"]):
            query_to_do="@is_production and @status_approved"

            if("recon-2018" in order["VersionSet"]):
                query_to_do="@is_2018production and @status_approved"

            if("recon-2019" in order["VersionSet"]):
                query_to_do="@is_dirc_production and @status_approved"
    
            if(order["RCDBQuery"] != ""):
                query_to_do=order["RCDBQuery"]
    
            print("RCDB_QUERY IS: "+str(query_to_do))
            rcdb_db = rcdb.RCDBProvider("mysql://rcdb@hallddb.jlab.org/rcdb")

            try:
                runList=rcdb_db.select_runs(str(query_to_do),order["RunNumLow"],order["RunNumHigh"]).get_values(['event_count'],True)
                print("RunList:",runList)
                #str(order["RunNumLow"])
                if runList == [[]]:
                    print("No runs found for this query")
                    output="oh no!!!"
                    errors="No runs found for this query"
                    RunNumber=-1
                else:
                    RunNumber=str(runList[0][0])
               
            except Exception as e:
                print(e)
                output=e
                errors=e
                RunNumber=-1
                pass
        
    
    #if(order["ReactionLines"][0:5]=="file:")
    #if order["RunNumLow"] != order["RunNumHigh"] :
    #    RunNumber = RunNumber + "-" + str(order["RunNumHigh"])
        pwd=os.getcwd()
        if RunNumber != -1:
            cleangen=1
            if order["SaveGeneration"]==1:
                cleangen=0

            cleangeant=1
            if order["SaveGeant"]==1:
                cleangeant=0
    
            cleansmear=1
            if order["SaveSmear"]==1:
                cleansmear=0
    
            cleanrecon=1
            if order["SaveReconstruction"]==1:
                cleanrecon=0

            test_number=500

            if(order["ID"]==2531):
                test_number=50
            command=MCWRAPPER_BOT_HOME+"/gluex_MC.py "+pwd+"/"+"MCDispatched_"+str(ID)+".config "+str(RunNumber)+" "+str(test_number)+" per_file=250000 base_file_number=0"+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=0 tobundle=0"
            print(command)
        
    # print (command+command2).split(" ")
        my_env=None
        print(versionSet)
    #if(versionSet != ""):
    #    myclean=source("/group/halld/Software/build_scripts/gluex_env_clean.csh")
    #    my_env=source("/group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/halld_versions/"+versionSet)
    #    my_env["MCWRAPPER_CENTRAL"]=MCWRAPPER_BOT_HOME

    #print(my_env)
    #if "" in my_env:
    #    split_kv=my_env[""].split("\n")
    #    absorbed=split_kv[len(split_kv)-1].split("=")
    #    print(absorbed)
    #    del my_env[""]
    #    my_env[absorbed[0]]=absorbed[1]
    #print(my_env)
        try:
            f=open('TestProject_runscript_'+str(ID)+'.sh','w')
            f.write("#!/bin/bash -l"+"\n")
            f.write("export SHELL=/bin/bash"+"\n")
            f.write("source /group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/halld_versions/"+versionSet+"\n")
            f.write("export MCWRAPPER_CENTRAL="+MCWRAPPER_BOT_HOME+"\n")
            f.write(command)
            f.close()
        except Exception as e:
            print(e)
            pass
    

        output="Error in rcdb query"
        errors="Error in rcdb query:"+str(query_to_do)
        sing_img="/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1"
        print("singularity exec --cleanenv --bind "+pwd+":"+pwd+" --bind /osgpool/halld/"+runner_name+":/osgpool/halld/"+runner_name+" --bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper "+sing_img+" /bin/sh "+pwd+"/TestProject_runscript_"+str(ID)+".sh")
        if RunNumber != -1:
            p = Popen("singularity exec --cleanenv --bind "+pwd+":"+pwd+" --bind /osgpool/halld/"+runner_name+":/osgpool/halld/"+runner_name+" --bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper "+ sing_img +" /bin/sh "+pwd+"/TestProject_runscript_"+str(ID)+".sh", env=my_env ,stdin=PIPE,stdout=PIPE, stderr=PIPE,bufsize=-1,shell=True)
            output, errors = p.communicate()
    

    #print [p.returncode,errors,output]
        output=str(output).replace('\\n', '\n')
        errors=str(errors).replace('\\n', '\n')

        STATUS=output.find("Successfully completed")
    

    if(STATUS!=-1):
        try:
            updatequery="UPDATE Project SET Tested=1, OutputLocation=\""+new_full_dirname+"\" WHERE ID="+str(ID)+";"
            curs.execute(updatequery)
            conn.commit()
            if(newLoc != "True"):
                updateOrderquery="UPDATE Project SET Generator_Config=\""+newLoc+"\" WHERE ID="+str(ID)+";"
                print(updateOrderquery)
                curs.execute(updateOrderquery)
                conn.commit()
        except Exception as e:
            print(e)
            pass
            #conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
            #curs=conn.cursor(MySQLdb.cursors.DictCursor)
        
        print(bcolors.OKGREEN+"TEST SUCCEEDED"+bcolors.ENDC)
        print("rm -rf "+order["OutputLocation"])
        #status = subprocess.call("rm -rf "+order["OutputLocation"],shell=True)
    else:
        try:
            updatequery="UPDATE Project SET Tested=-1"+" WHERE ID="+str(ID)+";"
            curs.execute(updatequery)
            conn.commit()
        except Exception as e:
            print(e)
            pass
        
        print(bcolors.FAIL+"TEST FAILED"+bcolors.ENDC)
        print("rm -rf "+order["OutputLocation"])
    #results_array=results_q.get()
    #results_array[index]=[output,STATUS,errors,row]
    #results_q.put(results_array)
    
    
    status=[output,STATUS,errors]
    #status=["RCDB QUERY: "+query_to_do+" is invalid",STATUS,"RCDB QUERY: "+query_to_do+" is invalid"]


    #if output=="Dispatch_Failure" and errors=="Dispatch_Failure":
    #    status=[output,STATUS,errors]
    print("status:",status)
    if(status[1]!=-1):
        #print "TEST success"
        #EMAIL SUCCESS AND DISPATCH
        #print("YAY TESTED")
        print(MCWRAPPER_BOT_HOME+"/Utilities/MCDispatcher.py dispatch -rlim -sys OSG "+str(row['ID']))
        subprocess.call(MCWRAPPER_BOT_HOME+"/Utilities/MCDispatcher.py dispatch -rlim -sys OSG "+str(row['ID']),shell=True)
    else:
        #print("BOO TESTED")
        #EMAIL FAIL AND LOG
        #print("echo 'Your Project ID "+str(row['ID'])+" failed the to properly test.  The log information is reproduced below:\n\n\n"+status[0]+"' | mail -s 'Project ID #"+str(row['ID'])+" Failed test' "+str(row['Email']))
        try:
            print("MAILING\n")
            msg = EmailMessage()
            print(status[0])
            print(status[2])
            msg.set_content('Your Project ID '+str(row['ID'])+' failed the test.  Please correct this issue by following the link: '+'https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill='+str(row['ID'])+'&mod=1'+'.  Do NOT resubmit this request.  Write tbritton@jlab.org for additional assistance\n\n The log information is reproduced below:\n\n\n'+str(status[0])+'\n\n\nErrors:\n\n\n'+str(status[2]))
            print("SET CONTENT")
            msg['Subject'] = 'MC Project ID #'+str(row['ID'])+' Failed to test properly'
            print("SET SUB")
            msg['From'] = str('MCwrapper-bot')
            print("SET FROM")

            msg['To'] = str(row['Email'])#str("tbritton@jlab.org")#
            print("SET SUB TO FROM")
            # Send the message via our own SMTP server.                                                                                                                                                                        
            s = smtplib.SMTP('localhost')
            #print(msg)
            print("SENDING")
            s.send_message(msg)
            print("SENT")
            s.quit() 
            try:    
                copy=open("/osgpool/halld/"+runner_name+"/REQUESTED_FAIL_MAILS/email_"+str(row['ID'])+".log", "w+")
                copy.write('The log information is reproduced below:\n\n\n'+str(status[0])+'\n\n\nErrors:\n\n\n'+str(status[2]))
                copy.close()
            except Exception as e:
                print(e)
                pass     
            #subprocess.call("echo 'Your Project ID "+str(row['ID'])+" failed the test.  Please correct this issue by following the link: "+"https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill="+str(row['ID'])+"&mod=1" +" .  Do NOT resubmit this request.  Write tbritton@jlab.org for additional assistance\n\n The log information is reproduced below:\n\n\n"+status[0]+"\n\n\n"+status[2]+"' | mail -s 'Project ID #"+str(row['ID'])+" Failed test' "+str(row['Email']),shell=True)
        except:
            print("UH OH MAILING")
            log = open("/osgpool/halld/"+runner_name+"/"+str(row['ID'])+".err", "w+")
            log.write("this was broke: \n" + str(status[2]))
            log.write("this was broke: \n" + str(status[0]))
            log.close()

    return status#[output,STATUS,errors]

def TestProject(ID,versionSet,commands_to_call=""):

    mktestdir="mkdir -p TestProj_"+str(ID)
    subprocess.call(mktestdir,shell=True)
    os.chdir("./TestProj_"+str(ID))
    subprocess.call("rm -f MCDispatched_"+str(ID)+".config", shell=True)
    print("TESTING PROJECT "+str(ID))
    query = "SELECT * FROM Project WHERE ID="+str(ID)
    curs.execute(query) 
    rows=curs.fetchall()
    order=rows[0]

    origOutLoc=order["OutputLocation"]
    orig_dirname=origOutLoc.split("/")[-2]
    new_dirname="_".join(orig_dirname.split("_")[:-1])+"_"+str(ID)
    new_full_dirname=origOutLoc.replace(orig_dirname,new_dirname)
    
    print("========================")
    print(order["Generator_Config"])
    newLoc=CheckGenConfig(order)
    print(order["Generator_Config"])
    print("========================")
    print(newLoc)
    if(newLoc!="True"):
        curs.execute(query) 
        rows=curs.fetchall()
        order=rows[0]

    if(order["RunNumHigh"] != order["RunNumLow"] and order["Generator"]=="file:"):
        updatequery="UPDATE Project SET Tested=-1"+" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()

        print(bcolors.FAIL+"TEST FAILED"+bcolors.ENDC)
        print("rm -rf "+order["OutputLocation"])

        return ["oh no!!!",-1,"MCwrapper cannot currently handle an input file with many run numbers properly"]

    WritePayloadConfig(order,newLoc)
    RunNumber=str(order["RunNumLow"])
    

    if(order["RunNumLow"] != order["RunNumHigh"]):
        query_to_do="@is_production and @status_approved"

        if("recon-2018" in order["VersionSet"]):
            query_to_do="@is_2018production and @status_approved"

        if("recon-2019" in order["VersionSet"]):
            query_to_do="@is_dirc_production and @status_approved"
    
        if(order["RCDBQuery"] != ""):
            query_to_do=order["RCDBQuery"]
    
    
        print("RCDB_QUERY IS: "+str(query_to_do))
        #print("run selecting currently broken.  RCDB: 'basestring' not defined.  Testing first runnumber only")
        rcdb_db = rcdb.RCDBProvider("mysql://rcdb@hallddb.jlab.org/rcdb")
        try:
            print(str(query_to_do)+" | "+str(int(order["RunNumLow"]))+" | "+str(int(order["RunNumHigh"])))
            runList=rcdb_db.select_runs(str(query_to_do),order["RunNumLow"],order["RunNumHigh"]).get_values(['event_count'],True)
            print("RunList:",runList)
            RunNumber=str(runList[0][0])
            #runtable = rcdbdb.select_runs(str(query_to_do),int(order["RunNumLow"]),int(order["RunNumHigh"])).get_values(['event_count'],True)
        
        
        except Exception as e:
            
            updatequery="UPDATE Project SET Tested=-1"+" WHERE ID="+str(ID)+";"
            print(updatequery)
            curs.execute(updatequery)
            conn.commit()
        
            print(bcolors.FAIL+"TEST FAILED"+bcolors.ENDC)
            print("rm -rf "+order["OutputLocation"])
            try:
                print("MAILING\n")
                msg = EmailMessage()
                e="RCDB Query failed: "+str(query_to_do)+"\n"
                print("Errors:",e)
                msg.set_content('Your Project ID '+str(order['ID'])+' failed the test.  Please correct this issue by following the link: '+'https://halldweb.jlab.org/gluex_sim/SubmitSim.html?prefill='+str(order['ID'])+'&mod=1'+'.  Do NOT resubmit this request.  Write tbritton@jlab.org for additional assistance\n\n The log information is reproduced below:\n\n\n'+str("There was a problem with the RCDB query provided")+'\n\n\nErrors:\n\n\n'+str(e))
                print("SET CONTENT")
                msg['Subject'] = 'Project ID #'+str(order['ID'])+' Failed to test properly'
                print("SET SUB")
                msg['From'] = str('MCwrapper-bot')
                print("SET FROM")

                msg['To'] = str(order['Email'])#str("tbritton@jlab.org")#
                print("SET SUB TO FROM")
                # Send the message via our own SMTP server.                                                                                                                                                                        
                s = smtplib.SMTP('localhost')
                #print(msg)
                print("SENDING")
                #s.send_message(msg)
                s.quit()     
                copy=open("/osgpool/halld/"+runner_name+"/REQUESTED_FAIL_MAILS/email_"+str(order['ID'])+".log", "w+")
                copy.write('The log information is reproduced below:\n\n\n'+str("There was a problem with the RCDB query provided")+'\n\n\nErrors:\n\n\n'+str(e))
                copy.close()
            except Exception as me:
                print(me)
                pass
            return ["Problem with rcdb query",-1,e]

        #print(runtable)
        
        #RunNumber=str(runList[0][0])

        
        
        #try:
        #    runList=rcdb_db.select_runs(str(query_to_do),order["RunNumLow"],order["RunNumHigh"]).get_values(['event_count'],True)
        #    print("RunList:",runList)
        #    RunNumber=str(runList[0][0])#str(order["RunNumLow"])
        #except Exception as e:
        #    print(e)
        #    output=e
        #    errors=e
        #    RunNumber=-1
        #    pass    

    #if order["RunNumLow"] != order["RunNumHigh"] :
    #    RunNumber = RunNumber + "-" + str(order["RunNumHigh"])

    cleangen=1
    if order["SaveGeneration"]==1:
        cleangen=0

    cleangeant=1
    if order["SaveGeant"]==1:
        cleangeant=0
    
    cleansmear=1
    if order["SaveSmear"]==1:
        cleansmear=0
    
    cleanrecon=1
    if order["SaveReconstruction"]==1:
        cleanrecon=0

    pwd=os.getcwd()
    command=MCWRAPPER_BOT_HOME+"/gluex_MC.py "+pwd+"/MCDispatched_"+str(ID)+".config "+str(RunNumber)+" "+str(500)+" per_file=250000 base_file_number=0"+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=0 tobundle=0"
    print(command)
    STATUS=-1
    # print (command+command2).split(" ")
    my_env=None
    #print(versionSet)
    #if(versionSet != ""):
    #    my_env=source("/group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/halld_versions/"+versionSet)
    #    my_env["MCWRAPPER_CENTRAL"]=MCWRAPPER_BOT_HOME

    #print(my_env)
    #if "" in my_env:
    #    split_kv=my_env[""].split("\n")
    #    absorbed=split_kv[len(split_kv)-1].split("=")
    #    print(absorbed)
    #    del my_env[""]
    #    my_env[absorbed[0]]=absorbed[1]
    #print(my_env)
    f=open('TestProject_runscript_'+str(ID)+'.sh','w')
    f.write("#!/bin/bash -l"+"\n")
    f.write("export SHELL=/bin/bash"+"\n")
    f.write("source /group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/halld_versions/"+versionSet+"\n")
    f.write("export MCWRAPPER_CENTRAL="+MCWRAPPER_BOT_HOME+"\n")
    f.write(command)
    f.close()

   
    print("singularity exec --cleanenv --bind "+pwd+":"+pwd+" --bind /osgpool/halld/"+runner_name+":/osgpool/halld/"+runner_name+" --bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper /cvmfs/singularity.opensciencegrid.org/markito3/gluex_docker_prod:latest /bin/sh "+pwd+"/TestProject_runscript_"+str(ID)+".sh")
    if RunNumber != -1:
        p = Popen("singularity exec --cleanenv --bind "+pwd+":"+pwd+" --bind /osgpool/halld/"+runner_name+":/osgpool/halld/"+runner_name+" --bind /group/halld/:/group/halld/ --bind /scigroup/mcwrapper/gluex_MCwrapper:/scigroup/mcwrapper/gluex_MCwrapper /cvmfs/singularity.opensciencegrid.org/markito3/gluex_docker_prod:latest /bin/sh "+pwd+"/TestProject_runscript_"+str(ID)+".sh", env=my_env ,stdin=PIPE,stdout=PIPE, stderr=PIPE,bufsize=-1,shell=True)
    
    #print p
    #print "p defined"
    output, errors = p.communicate()
    
    #print [p.returncode,errors,output]
    output=str(output).replace('\\n', '\n')
    errors=str(errors).replace('\\n', '\n')
    STATUS=output.find("Successfully completed")
    

    if(STATUS!=-1):
        updatequery="UPDATE Project SET Tested=1, OutputLocation=\""+new_full_dirname+"\" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()

        if(newLoc != "True"):
            updateOrderquery="UPDATE Project SET Generator_Config=\""+newLoc+"\" WHERE ID="+str(ID)+";"
            print(updateOrderquery)
            curs.execute(updateOrderquery)
            conn.commit()
        
        print(bcolors.OKGREEN+"TEST SUCCEEDED"+bcolors.ENDC)
        print("rm -rf "+order["OutputLocation"])
        #status = subprocess.call("rm -rf "+order["OutputLocation"],shell=True)
    else:
        updatequery="UPDATE Project SET Tested=-1"+" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()
        
        print(bcolors.FAIL+"TEST FAILED"+bcolors.ENDC)
        print("rm -rf "+order["OutputLocation"])
    return [output,STATUS,errors]

def DispatchToInteractive(ID,order,PERCENT):
    subprocess.call("rm -f MCDispatched_"+str(ID)+".config", shell=True)
    WritePayloadConfig(order,"True")
    RunNumber=str(order["RunNumLow"])
    if order["RunNumLow"] != order["RunNumHigh"] :
        RunNumber = RunNumber + "-" + str(order["RunNumHigh"])


    cleangen=1
    if order["SaveGeneration"]==1:
        cleangen=0

    cleangeant=1
    if order["SaveGeant"]==1:
        cleangeant=0
    
    cleansmear=1
    if order["SaveSmear"]==1:
        cleansmear=0
    
    cleanrecon=1
    if order["SaveReconstruction"]==1:
        cleanrecon=0

    # CHECK THE OUTSTANDING JOBS VERSUS ORDER
    TotalOutstanding_Events_check = "SELECT SUM(NumEvts), MAX(FileNumber) FROM Jobs WHERE IsActive=1 && Project_ID="+str(ID)+" && ID IN (SELECT Job_ID FROM Attempts WHERE ExitCode=0);"
    curs.execute(TotalOutstanding_Events_check)
    TOTALOUTSTANDINGEVENTS = curs.fetchall()

    RequestedEvents_query = "SELECT NumEvents FROM Project WHERE ID="+str(ID)+";"
    curs.execute(RequestedEvents_query)
    TotalRequestedEventsret = curs.fetchall()
    TotalRequestedEvents= TotalRequestedEventsret[0]["NumEvents"]

    OutstandingEvents=0
    if(TOTALOUTSTANDINGEVENTS[0]["SUM(NumEvts)"]):
        OutstandingEvents=TOTALOUTSTANDINGEVENTS[0]["SUM(NumEvts)"]
    
    FileNumber_NewJob=int(-1)
    if(TOTALOUTSTANDINGEVENTS[0]["MAX(FileNumber)"]):
        FileNumber_NewJob=TOTALOUTSTANDINGEVENTS[0]["MAX(FileNumber)"]

    FileNumber_NewJob+=1

    NumEventsToProduce=min(int(float(TotalRequestedEvents)*float(PERCENT)),TotalRequestedEvents-OutstandingEvents)
    
    percentDisp=float(NumEventsToProduce+OutstandingEvents)/float(TotalRequestedEvents)

    if NumEventsToProduce > 0:
        updatequery="UPDATE Project SET Is_Dispatched='"+str(percentDisp) +"', Dispatched_Time="+"NOW() "+"WHERE ID="+str(ID)+";"
        #print updatequery
        curs.execute(updatequery)
        conn.commit()
        command=MCWRAPPER_BOT_HOME+"/gluex_MC.py MCDispatched_"+str(ID)+".config "+str(RunNumber)+" "+str(NumEventsToProduce)+" per_file=250000 base_file_number="+str(FileNumber_NewJob)+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=0 tobundle=0"
        print(command)
        status = subprocess.call(command, shell=True)
    else:
        print("All jobs submitted for this order")

def DispatchToSWIF(ID,order,PERCENT):
    status = subprocess.call("cp "+MCWRAPPER_BOT_HOME+"/examples/SWIFShell.config ./MCDispatched_"+str(ID)+".config", shell=True)
    WritePayloadConfig(order,"True")
    RunNumber=str(order["RunNumLow"])
    if order["RunNumLow"] != order["RunNumHigh"] :
        RunNumber = RunNumber + "-" + str(order["RunNumHigh"])


    cleangen=1
    if order["SaveGeneration"]==1:
        cleangen=0

    cleangeant=1
    if order["SaveGeant"]==1:
        cleangeant=0
    
    cleansmear=1
    if order["SaveSmear"]==1:
        cleansmear=0
    
    cleanrecon=1
    if order["SaveReconstruction"]==1:
        cleanrecon=0

    # CHECK THE OUTSTANDING JOBS VERSUS ORDER
    TotalOutstanding_Events_check = "SELECT SUM(NumEvts), MAX(FileNumber) FROM Jobs WHERE IsActive=1 && Project_ID="+str(ID)+" && ID IN (SELECT Job_ID FROM Attempts WHERE ExitCode=0);"
    curs.execute(TotalOutstanding_Events_check)
    TOTALOUTSTANDINGEVENTS = curs.fetchall()

    RequestedEvents_query = "SELECT NumEvents FROM Project WHERE ID="+str(ID)+";"
    curs.execute(RequestedEvents_query)
    TotalRequestedEventsret = curs.fetchall()
    TotalRequestedEvents= TotalRequestedEventsret[0]["NumEvents"]

    OutstandingEvents=0
    if(TOTALOUTSTANDINGEVENTS[0]["SUM(NumEvts)"]):
        OutstandingEvents=TOTALOUTSTANDINGEVENTS[0]["SUM(NumEvts)"]
    
    FileNumber_NewJob=int(-1)
    if(TOTALOUTSTANDINGEVENTS[0]["MAX(FileNumber)"]):
        FileNumber_NewJob=TOTALOUTSTANDINGEVENTS[0]["MAX(FileNumber)"]

    FileNumber_NewJob+=1

    NumEventsToProduce=min(int(float(TotalRequestedEvents)*float(PERCENT)),TotalRequestedEvents-OutstandingEvents)
    
    percentDisp=float(NumEventsToProduce+OutstandingEvents)/float(TotalRequestedEvents)

    if NumEventsToProduce > 0:
        updatequery="UPDATE Project SET Is_Dispatched='"+str(percentDisp) +"', Dispatched_Time="+"NOW() "+"WHERE ID="+str(ID)+";"
        #print updatequery
        curs.execute(updatequery)
        conn.commit()
        per_file_num=50000
        get_perfile_q="SELECT PerFile from Generator_perfiles where GenName=\""+order["Generator"]+"\";"
        curs.execute(get_perfile_q) 
        rows=curs.fetchall()
        try:
            per_file_num=rows[0]["PerFile"]
        except Exception as e:
            print(e)
            pass
        command=MCWRAPPER_BOT_HOME+"/gluex_MC.py MCDispatched_"+str(ID)+".config "+str(RunNumber)+" "+str(NumEventsToProduce)+" per_file="+str(per_file_num) +" base_file_number="+str(FileNumber_NewJob)+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=2 tobundle=0"
        print(command)
        status = subprocess.call(command, shell=True)
    else:
        print("All jobs submitted for this order")

def WriteConfig(ID):
    query = "SELECT * FROM Project WHERE ID="+str(ID)
    curs.execute(query) 
    rows=curs.fetchall()
    print(rows)
    newLoc=CheckGenConfig(rows[0])
    WritePayloadConfigString(rows[0],newLoc)
    #status = subprocess.call("cp "+MCWRAPPER_BOT_HOME+"/examples/SWIFShell.config ./MCDispatched_"+str(ID)+".config", shell=True)
    #WritePayloadConfig(rows[0],"True")

def WritePayloadConfig(order,foundConfig,jobID=-1):
    #print("writing config file based on\n",order)
    if jobID==-1:
        MCconfig_file= open("MCDispatched_"+str(order['ID'])+".config","a")
    else:
        MCconfig_file= open("MCDispatched_"+str(jobID)+".config","a")

    MCconfig_file.write("PROJECT="+str(order["Exp"])+"\n")

    if str(order["Exp"]) == "CPP":
        MCconfig_file.write("VARIATION=mc_cpp"+"\n")
        MCconfig_file.write("FLUX_TO_GEN=cobrems"+"\n")
    elif str(order["Exp"]) == "JEF":
        MCconfig_file.write("VARIATION=mc_JEF"+"\n")
        MCconfig_file.write("FLUX_TO_GEN=cobrems"+"\n")
        MCconfig_file.write("eBEAM_ENERGY=11.6"+"\n")
        MCconfig_file.write("eBEAM_CURRENT=0.35"+"\n")
        MCconfig_file.write("RADIATOR_THICKNESS=50.e-06"+"\n")
        MCconfig_file.write("COHERENT_PEAK=8.6"+"\n")

    splitlist=order["OutputLocation"].split("/")
    MCconfig_file.write("WORKFLOW_NAME="+splitlist[len(splitlist)-2]+"\n")
    MCconfig_file.write(order["Config_Stub"]+"\n")
    MinE=str(order["GenMinE"])
    if len(MinE) > 5:
        cutnum=len(MinE)-5
        MinE = MinE[:-cutnum]
    MaxE=str(order["GenMaxE"])
    if len(MaxE) > 5:
        cutnum=len(MaxE)-5
        MaxE = MaxE[:-cutnum]
    MCconfig_file.write("GEN_MIN_ENERGY="+MinE+"\n")
    MCconfig_file.write("GEN_MAX_ENERGY="+MaxE+"\n")

    if str(order["GenFlux"]) == "cobrems":
        MCconfig_file.write("FLUX_TO_GEN=cobrems"+"\n")

    if(order["CoherentPeak"] != None):
        MCconfig_file.write("COHERENT_PEAK="+str(order["CoherentPeak"])+"\n")
    else:
        MCconfig_file.write("COHERENT_PEAK=rcdb"+"\n")

    if str(order["Generator"]) == "file:":
        if foundConfig == "True":
            MCconfig_file.write("GENERATOR="+str(order["Generator"])+"/"+str(order["Generator_Config"])+"\n")
        else:
            MCconfig_file.write("GENERATOR="+str(order["Generator"])+"/"+foundConfig+"\n")
    else:
        MCconfig_file.write("GENERATOR="+str(order["Generator"])+"\n")
        print(order["Generator_Config"])
        if foundConfig=="True":
            MCconfig_file.write("GENERATOR_CONFIG="+str(order["Generator_Config"])+"\n")
        else:
            MCconfig_file.write("GENERATOR_CONFIG="+foundConfig+"\n")

    print("post genconfig!",order["GenPostProcessing"])
    
    if(order["GenPostProcessing"] != None and order["GenPostProcessing"] != ""):
        fileError=False
        parseGenPostProcessing=order["GenPostProcessing"].split(":")
        newGenPost_str=parseGenPostProcessing[0]
        print("newGenPost_str",newGenPost_str)
        for i in range(1,len(parseGenPostProcessing)):
            print("parseGenPostProcessing[i]",parseGenPostProcessing[i])
            if parseGenPostProcessing[i].strip() != "Default":

                copy_loc="ifarm1801-ib"
                if(socket.gethostname()=="scosg2201.jlab.org"):
                    copy_loc="ifarm1801"
                print("scp "+runner_name+"@"+copy_loc+":"+parseGenPostProcessing[i]+" "+"/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_genpost_"+str(i)+".config")
                try:
                    subprocess.call("scp "+runner_name+"@"+copy_loc+":"+parseGenPostProcessing[i]+" "+"/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_genpost_"+str(i)+".config", shell=True)
                except Exception as e:
                    print("Error in copying gen post processing file:",e)
                    pass

                print("checking for config file:","/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_genpost_"+str(i)+".config")
                if( os.path.exists("/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_genpost_"+str(i)+".config")):
                    newGenPost_str+=":/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_genpost_"+str(i)+".config"
                    
                    #fileError=False
                else:
                    print("Error finding a gen post processing file:",parseGenPostProcessing[i] ,"not found")
                    fileError=True
            else:
                newGenPost_str+=":Default"
       
        print("file Error:",fileError)
        #exit(1)
        if fileError==False:
            #update database genpost
            update_str="UPDATE Project SET GenPostProcessing='"+newGenPost_str+"' WHERE ID="+str(order["ID"])
            print(update_str)
            curs.execute(update_str)
            conn.commit()
        else:
            print("Could not find one or more generator post processing files!")
            msg = EmailMessage()
            msg.set_content("Could not test the project because MCwrapper-bot could not copy the following file: "+parseGenPostProcessing[i]+"\n This may be due to a lack of permissions for "+runner_name+" to read from the containing directory or the file itself may not exist.\n Shortly you will receive a second email that the actual test has failed, please use the link contained in the second email to correct this problem.")

            # me == the sender's email address                                                                                                                                                                                 
            # you == the recipient's email address                                                                                                                                                                             
            msg['Subject'] = 'GlueX MC Request #'+str(order['ID'])+' Could not be tested properly'
            msg['From'] = 'MCwrapper-bot'
            msg['To'] = str(order['Email'])

            # Send the message via our own SMTP server.                                                                                                                                                                        
            s = smtplib.SMTP('localhost')
            s.send_message(msg)
            s.quit()

            update_status_query="UPDATE Project SET Tested=-1 WHERE ID="+str(order["ID"])
            curs.execute(update_status_query)
            conn.commit()
            return
        MCconfig_file.write("GENERATOR_POSTPROCESS="+str(newGenPost_str)+"\n")


    MCconfig_file.write("GEANT_VERSION="+str(order["GeantVersion"])+"\n")
    MCconfig_file.write("NOSECONDARIES="+str(abs(order["GeantSecondaries"]-1))+"\n")
    MCconfig_file.write("BKG="+str(order["BKG"])+"\n")
    print(order["OutputLocation"])
    splitLoc=str(order["OutputLocation"]).split("/")
    print(splitLoc)
    outputstring="/".join(splitLoc[7:-1])
    #order["OutputLocation"]).split("/")[7]
    MCconfig_file.write("DATA_OUTPUT_BASE_DIR=/osgpool/halld/"+runner_name+"/REQUESTEDMC_OUTPUT/"+str(outputstring)+"\n")
    #print "FOUND CONFIG="+foundConfig


    print("PREIF", order["VersionSet"])
    query_to_do=""
    if(order["RunNumLow"] != order["RunNumHigh"]):
        query_to_do="@is_production and @status_approved"

        if("recon-2018" in order["VersionSet"]):
            query_to_do="@is_2018production and @status_approved"

        if("recon-2019" in order["VersionSet"]):
            query_to_do="@is_dirc_production and @status_approved"
    
        if(order["RCDBQuery"] != ""):
            query_to_do=order["RCDBQuery"]
    
    if(query_to_do != ""):
        MCconfig_file.write("RCDB_QUERY="+query_to_do+"\n")

    if(order["ReactionLines"] != ""):
        if(order["ReactionLines"][0:5] == "file:"):
            jana_config_file=order["ReactionLines"][5:]
            copy_loc="ifarm1801-ib"
            if(socket.gethostname()=="scosg2201.jlab.org"):
                copy_loc="ifarm1801"

            print("scp "+runner_name+"@"+copy_loc+":"+jana_config_file+" "+"/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config")
            subprocess.call("scp "+runner_name+"@"+copy_loc+":"+jana_config_file+" "+"/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config",shell=True)
            

            if(os.path.exists("/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config")):
                update_str="Update Project Set ReactionLines='file:/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config' where ID="+str(order["ID"])
                print(update_str)
                curs.execute(update_str)
                conn.commit()
            else:
                print("could not copy file",jana_config_file)
                
                msg = EmailMessage()
                msg.set_content("Could not test the project because MCwrapper-bot could not copy the following file: "+jana_config_file+"\n This may be due to a lack of permissions for "+runner_name+" to read from the containing directory or the file itself may not exist.\n Shortly you will receive a second email that the actual test has failed, please use the link contained in the second email to correct this problem.")

                # me == the sender's email address                                                                                                                                                                                 
                # you == the recipient's email address                                                                                                                                                                             
                msg['Subject'] = 'GlueX MC Request #'+str(order['ID'])+' Could not be tested properly'
                msg['From'] = 'MCwrapper-bot'
                msg['To'] = str(order['Email'])

                # Send the message via our own SMTP server.                                                                                                                                                                        
                s = smtplib.SMTP('localhost')
                s.send_message(msg)
                s.quit()
                pass

        else:
            jana_config_file=open("/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config","w")
            janaplugins="PLUGINS danarest,monitoring_hists,mcthrown_tree"
            if(order["ReactionLines"]):
                janaplugins+=",ReactionFilter\n"+order["ReactionLines"]
            else:
                janaplugins+="\n"
            jana_config_file.write(janaplugins)
            jana_config_file.close()


        MCconfig_file.write("CUSTOM_PLUGINS=file:/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config\n")

    
    MCconfig_file.write("ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"+str(order["VersionSet"])+"\n")
    print("ADD ANAVER TO PAYLOAD?")
    print(str(order["ANAVersionSet"]))
    if(order["ANAVersionSet"] != None and order["ANAVersionSet"] != "None" ):
        print("ADDING ANNAVER")
        MCconfig_file.write("ANA_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"+str(order["ANAVersionSet"])+"\n")
    MCconfig_file.close()

def DispatchToOSG(ID,order,PERCENT):
    print("Dispatching to OSG")
    status = subprocess.call("cp "+MCWRAPPER_BOT_HOME+"/examples/OSGShell.config ./MCDispatched_"+str(ID)+".config", shell=True)
    WritePayloadConfig(order,"True")

    RunNumber=str(order["RunNumLow"])
    if order["RunNumLow"] != order["RunNumHigh"] :
        RunNumber = RunNumber + "-" + str(order["RunNumHigh"])

    cleangen=1
    if order["SaveGeneration"]==1:
        cleangen=0

    cleangeant=1
    if order["SaveGeant"]==1:
        cleangeant=0
    
    cleansmear=1
    if order["SaveSmear"]==1:
        cleansmear=0
    
    cleanrecon=1
    if order["SaveReconstruction"]==1:
        cleanrecon=0


    updatequery="UPDATE Project SET Is_Dispatched='"+str(1.0) +"', Dispatched_Time="+"NOW() "+"WHERE ID="+str(ID)+";"
    #print updatequery
    curs.execute(updatequery)
    conn.commit()
    per_file_num=20000
    get_perfile_q="SELECT PerFile from Generator_perfiles where GenName=\""+order["Generator"]+"\";"
    curs.execute(get_perfile_q) 
    rows=curs.fetchall()
    try:
        per_file_num=rows[0]["PerFile"]
    except Exception as e:
        print(e)
        pass
    command=MCWRAPPER_BOT_HOME+"/gluex_MC.py MCDispatched_"+str(ID)+".config "+str(RunNumber)+" "+str(order["NumEvents"])+" per_file="+str(per_file_num)+" base_file_number="+str(0)+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" logdir=/osgpool/halld/"+runner_name+"/REQUESTEDMC_LOGS/"+order["OutputLocation"].split("/")[7]+" batch=1 tobundle=0"
    print(command)
    status = subprocess.call(command, shell=True)
    
def WritePayloadConfigString(order,foundConfig):
    config_str=""

    config_str+="PROJECT="+str(order["Exp"])+"\n"

    if str(order["Exp"]) == "CPP":
        config_str+="VARIATION=mc_cpp"+"\n"
        config_str+="FLUX_TO_GEN=cobrems"+"\n"
    elif str(order["Exp"]) == "JEF":
        config_str+="VARIATION=mc_JEF"+"\n"
        config_str+="FLUX_TO_GEN=cobrems"+"\n"
        config_str+="eBEAM_ENERGY=11.6"+"\n"
        config_str+="eBEAM_CURRENT=0.35"+"\n"
        config_str+="RADIATOR_THICKNESS=50.e-06"+"\n"
        config_str+="COHERENT_PEAK=8.6"+"\n"    

    splitlist=order["OutputLocation"].split("/")
    config_str+="WORKFLOW_NAME="+splitlist[len(splitlist)-2]+"\n"
    config_str+=order["Config_Stub"]+"\n"
    MinE=str(order["GenMinE"])
    if len(MinE) > 5:
        cutnum=len(MinE)-5
        MinE = MinE[:-cutnum]
    MaxE=str(order["GenMaxE"])
    if len(MaxE) > 5:
        cutnum=len(MaxE)-5
        MaxE = MaxE[:-cutnum]
    config_str+="GEN_MIN_ENERGY="+MinE+"\n"
    config_str+="GEN_MAX_ENERGY="+MaxE+"\n"

    if str(order["GenFlux"]) == "cobrems":
        config_str+="FLUX_TO_GEN=cobrems"+"\n"

    if order["CoherentPeak"] is not None :
        config_str+="COHERENT_PEAK="+str(order["CoherentPeak"])+"\n"

    if str(order["Generator"]) == "file:":
        if foundConfig == "True":
            config_str+="GENERATOR="+str(order["Generator"])+"/"+str(order["Generator_Config"])+"\n"
        else:
            config_str+="GENERATOR="+str(order["Generator"])+"/"+foundConfig+"\n"
    else:
        config_str+="GENERATOR="+str(order["Generator"])+"\n"
        #print(order["Generator_Config"])
        if foundConfig=="True":
            config_str+="GENERATOR_CONFIG="+str(order["Generator_Config"])+"\n"
        else:
            config_str+="GENERATOR_CONFIG="+foundConfig+"\n"


    if(order["CoherentPeak"] != None):
        config_str+="COHERENT_PEAK="+str(order["CoherentPeak"])+"\n"
    else:
        config_str+="COHERENT_PEAK=rcdb"+"\n"

    if(order["GenPostProcessing"] != None and order["GenPostProcessing"] != ""):
        config_str+="GEN_POST_PROCESSING="+str(order["GenPostProcessing"])+"\n"
    

    config_str+="GEANT_VERSION="+str(order["GeantVersion"])+"\n"
    config_str+="NOSECONDARIES="+str(abs(order["GeantSecondaries"]-1))+"\n"
    config_str+="BKG="+str(order["BKG"])+"\n"
    #print(order["OutputLocation"])
    splitLoc=str(order["OutputLocation"]).split("/")
    #print(splitLoc)
    outputstring="/".join(splitLoc[7:-1])
    #order["OutputLocation"]).split("/")[7]
    config_str+="DATA_OUTPUT_BASE_DIR=/osgpool/halld/"+runner_name+"/REQUESTEDMC_OUTPUT/"+str(outputstring)+"\n"
    #print "FOUND CONFIG="+foundConfig

    if(order["RunNumLow"] != order["RunNumHigh"]):
        query_to_do="@is_production and @status_approved"

        if("recon-2018" in order["VersionSet"]):
            query_to_do="@is_2018production and @status_approved"

        if("recon-2019" in order["VersionSet"]):
            query_to_do="@is_dirc_production and @status_approved"
    
        if(order["RCDBQuery"] != ""):
            query_to_do=order["RCDBQuery"]

    config_str+="RCDB_QUERY="+query_to_do+"\n"
        

    if(order["ReactionLines"] != ""):
        if(order["ReactionLines"][0:5] != "file:"):
            #jana_config_file=open("/osgpool/halld/tbritton/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config","w")
            janaplugins="PLUGINS danarest,monitoring_hists,mcthrown_tree"
            if(order["ReactionLines"]):
                janaplugins+=",ReactionFilter\n"+order["ReactionLines"]
            else:
                janaplugins+="\n"
            #jana_config_file.write(janaplugins)
            #jana_config_file.close()
        config_str+="CUSTOM_PLUGINS=file:/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config\n"

    
    config_str+="ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"+str(order["VersionSet"])+"\n"
    #print("ADD ANAVER TO PAYLOAD?")
    #print(str(order["ANAVersionSet"]))
    if(order["ANAVersionSet"] != None and order["ANAVersionSet"] != "None" ):
        #print("ADDING ANNAVER")
        config_str+="ANA_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"+str(order["ANAVersionSet"])+"\n"
    #print("---------------------------------")
    print(config_str)
    return config_str

def main(argv):
    #print(argv)

    if(os.path.isfile("/osgpool/halld/"+runner_name+"/.ALLSTOP")==True):
        print("ALL STOP DETECTED")
        exit(1)

    numprocesses_running=subprocess.check_output(["echo `ps all -u "+runner_name+" | grep MCDispatcher.py | grep -v grep | wc -l`"], shell=True)
    #print(args)

    ID=-1
    MODE=""
    SYSTEM="NULL"
    PERCENT=1.0
    RUNNING_LIMIT_OVERRIDE=False
    argindex=-1


    for argu in argv:
        #print "ARGS"
        #print argu
        argindex=argindex+1

        if argindex == 1 or len(argv)==1:
            #print str(argv[0]).upper()
            MODE=str(argv[0]).upper()
            #print MODE

        if argindex == len(argv)-1:
            ID=argv[argindex]

        if argu[0] == "-":
            if argu == "-sys":
                SYSTEM=str(argv[argindex+1]).upper()
            if argu == "-percent":
                PERCENT=argv[argindex+1]
            if argu == "-rlim":
                RUNNING_LIMIT_OVERRIDE=True

    print("num running", int(numprocesses_running))
    if(int(numprocesses_running) <2 or RUNNING_LIMIT_OVERRIDE ):
       

        #print MODE
        #print SYSTEM
        #print ID
        print("RUNNING",MODE)
        if MODE == "DISPATCH":
            if ID != "All":
                DispatchProject(ID,SYSTEM,PERCENT)
            elif ID == "All":
                query = "SELECT ID FROM Project WHERE Is_Dispatched!='1.0'"
                curs.execute(query) 
                rows=curs.fetchall()
                for row in rows:
                    #print(row["ID"])
                    DispatchProject(row["ID"],SYSTEM,PERCENT)
        elif MODE == "VIEW":
            ListUnDispatched()
        elif MODE == "TEST":
            query = "SELECT Email,VersionSet,Tested,UName FROM Project WHERE ID="+str(ID)
            #print query
            curs.execute(query) 
            row=curs.fetchall()[0]
            status=TestProject(ID,row["VersionSet"],"")
            if(status[1]!=-1):
                subprocess.call(MCWRAPPER_BOT_HOME+"/Utilities/MCDispatcher.py dispatch -rlim -sys OSG "+str(ID),shell=True)
            else:
                f=open(str(ID)+".out","w+")
                f.write(str(status[0]))
                f.close()
                f=open(str(ID)+".err","w+")
                f.write(str(status[2]))
                f.close()
                
        elif MODE == "RETRYJOB":
            RetryJob(ID)
        elif MODE == "RETRYJOBS":
            RetryJobsFromProject(ID, False)
        elif MODE == "RETRYALLJOBS":
            RetryAllJobs(RUNNING_LIMIT_OVERRIDE)
        elif MODE == "CANCELJOB":
            CancelJob(ID)
        elif MODE == "AUTOLAUNCH":
            print("AUTOLAUNCHING NOW")
            AutoLaunch()
        elif MODE == "REMOVEJOBS":
            RemoveAllJobs()
        elif MODE == "WRITECONFIG":
            WriteConfig(ID)
        else:
            print("MODE NOT FOUND")

        
    conn.close()
        

if __name__ == "__main__":
   main(sys.argv[1:])
