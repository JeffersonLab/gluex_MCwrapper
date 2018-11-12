#!/usr/bin/env python
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


dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

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

def AutoLaunch():
    #print "in autolaunch"
    query = "SELECT ID,Email,VersionSet FROM Project WHERE Tested != -1 && Dispatched_Time is NULL;"
    #print query
    curs.execute(query) 
    rows=curs.fetchall()
    #print rows
    #print len(rows)
    for row in rows:
        commands_to_call="source /group/halld/Software/build_scripts/gluex_env_boot_jlab.sh;"
        commands_to_call+="gxclean;"
        #subprocess.call("source /group/halld/Software/build_scripts/gluex_env_boot_jlab.sh;",shell=True)                                                                                                          
        #subprocess.call("gxclean",shell=True)                                                                                                                                                                     
        commands_to_call+="source /group/halld/Software/build_scripts/gluex_env_jlab.sh /group/halld/www/halldweb/html/dist/"+str(row["VersionSet"])+";"
        commands_to_call+="export MCWRAPPER_CENTRAL=/osgpool/halld/tbritton/gluex_MCwrapper/;"
        commands_to_call+="export PATH=/apps/bin:${PATH};"
        subprocess.call(commands_to_call,shell=True) 
        status=TestProject(row['ID'])

        #print "STATUS IS"
        #print status[0]
        #print status[1]
        if(status[1]!=-1):
            #print "TEST success"
            #EMAIL SUCCESS AND DISPATCH
            subprocess.call("/osgpool/halld/tbritton/gluex_MCwrapper/Utilities/MCDispatcher.py dispatch -sys OSG "+str(row['ID']),shell=True)
        else:
            #EMAIL FAIL AND LOG
            print "echo 'Your Project ID "+str(row['ID'])+" failed the to properly test.  The log information is reproduced below:\n\n\n"+status[0]+"' | mail -s 'Project ID #"+str(row['ID'])+" Failed test' "+str(row['Email'])
            subprocess.call("echo 'Your Project ID "+str(row['ID'])+" failed the test.  Please correct this issue and do NOT resubmit this request.  Write tbritton@jlab.org for assistance or if you are ready for a retest.\n\n The log information is reproduced below:\n\n\n"+status[0]+"' | mail -s 'Project ID #"+str(row['ID'])+" Failed test' "+str(row['Email']),shell=True)
            #print status[0]
            



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
    

def RetryJobsFromProject(ID):
    query= "SELECT * FROM Attempts WHERE ID IN (SELECT Max(ID) FROM Attempts GROUP BY Job_ID) && Job_ID IN (SELECT ID FROM Jobs WHERE IsActive=1 && Project_ID="+str(ID)+");"
    curs.execute(query) 
    rows=curs.fetchall()
   
    i=0
    for row in rows:
        
        if (row["BatchSystem"]=="SWIF"):
            if((row["Status"] == "succeeded" and row["ExitCode"] != 0) or row["Status"]=="problems"):
                RetryJob(row["Job_ID"])
                i=i+1
        elif (row["BatchSystem"]=="OSG"):
            #print "=========================="
            #print row
            #print row["Status"]
            #print row["ExitCode"]
            #print "=========================="
            if(row["Status"] == "4" and row["ExitCode"] != 0) or row["Status"] == "5":
                RetryJob(row["Job_ID"])
                i=i+1
    print "retried "+str(i)+" Jobs"

#def DoMissingJobs(ID,SYS):
#    query="SELECT ID FROM Jobs where ID NOT IN (SELECT Job_ID FROM Attempts) && IsActive=1 && Project_ID="+str(ID)+";"
#    curs.execute(query) 
#    rows=curs.fetchall()
    #GET PROJECT INFO
    
#    for row in rows:
#        if(SYS == "OSG"):
        #TREAT LIKE NEW PROJECT WITH JUST THE JOB



def RetryJob(ID):
    #query = "SELECT * FROM Attempts WHERE Job_ID="+str(ID)
    query= "SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts,Jobs WHERE Attempts.Job_ID = "+str(ID)
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

    if(rows[0]["BatchSystem"] == "SWIF"):
        splitL=len(proj[0]["OutputLocation"].split("/"))
        command = "swif retry-jobs -workflow "+proj[0]["OutputLocation"].split("/")[splitL-2]+" "+rows[0]["BatchJobID"]
        print command
        status = subprocess.call(command, shell=True)
    elif(rows[0]["BatchSystem"] == "OSG"):
        #print "OSG JOB FOUND"
        status = subprocess.call("cp $MCWRAPPER_CENTRAL/examples/OSGShell.config ./MCDispatched.config", shell=True)
        WritePayloadConfig(proj[0],"True")
        command="$MCWRAPPER_CENTRAL/gluex_MC.py MCDispatched.config "+str(job[0]["RunNumber"])+" "+str(job[0]["NumEvts"])+" per_file=50000 base_file_number="+str(job[0]["FileNumber"])+" generate="+str(proj[0]["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(proj[0]["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(proj[0]["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(proj[0]["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid=-"+str(ID)+" batch=1"
        #print(command)
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
    fileSTR=order["Generator_Config"]
    file_split=fileSTR.split("/")
    name=file_split[len(file_split)-1]
    #print name
    #print fileSTR
    if(os.path.isfile(fileSTR)==False and socket.gethostname() == "scosg16.jlab.org" ):
        copyTo="/osgpool/halld/tbritton/REQUESTEDMC_CONFIGS/"
        subprocess.call("scp tbritton@ifarm1402:"+fileSTR+" "+copyTo+str(ID)+"_"+name,shell=True)
        #subprocess.call("rsync -ruvt ifarm1402:"+fileSTR+" "+copyTo,shell=True)
        order["Generator_Config"]=copyTo+name
        return copyTo+str(ID)+"_"+name
    elif os.path.isfile(fileSTR)==False and socket.gethostname() != "scosg16.jlab.org":
        return copyTo+str(ID)+"_"+name

    return "True"


def TestProject(ID,commands_to_call=""):
    subprocess.call("rm -f MCDispatched.config", shell=True)
    print "TESTING PROJECT "+str(ID)
    query = "SELECT * FROM Project WHERE ID="+str(ID)
    curs.execute(query) 
    rows=curs.fetchall()
    order=rows[0]
    #print "========================"
    #print order["Generator_Config"]
    newLoc=CheckGenConfig(order)
    #print order["Generator_Config"]
    #print "========================"
    #print newLoc
    if(newLoc!="True"):
        curs.execute(query) 
        rows=curs.fetchall()
        order=rows[0]

    WritePayloadConfig(order,newLoc)
    RunNumber=str(order["RunNumLow"])
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

    command="$MCWRAPPER_CENTRAL/gluex_MC.py MCDispatched.config "+str(RunNumber)+" "+str(10)+" per_file=250000 base_file_number=0"+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=0"
    print(command)
    STATUS=-1
   # print (command+command2).split(" ")
    p = Popen(commands_to_call+command, stdin=PIPE,stdout=PIPE, stderr=PIPE,bufsize=-1,shell=True)
    #print p
    #print "p defined"
    output, errors = p.communicate()
    
    #print [p.returncode,errors,output]
    output=output.replace('\\n', '\n')
    
    STATUS=output.find("Successfully completed")
    

    if(STATUS!=-1):
        updatequery="UPDATE Project SET Tested=1"+" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()
        if(newLoc != "True"):
            updateOrderquery="UPDATE Project SET Generator_Config=\""+newLoc+"\" WHERE ID="+str(ID)+";"
            print updateOrderquery
            curs.execute(updateOrderquery)
            conn.commit()
        
        print bcolors.OKGREEN+"TEST SUCCEEDED"+bcolors.ENDC
        print "rm -rf "+order["OutputLocation"]
        #status = subprocess.call("rm -rf "+order["OutputLocation"],shell=True)
    else:
        updatequery="UPDATE Project SET Tested=-1"+" WHERE ID="+str(ID)+";"
        curs.execute(updatequery)
        conn.commit()
        
        print bcolors.FAIL+"TEST FAILED"+bcolors.ENDC
        print "rm -rf "+order["OutputLocation"]
    return [output,STATUS]

def DispatchToInteractive(ID,order,PERCENT):
    subprocess.call("rm -f MCDispatched.config", shell=True)
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
        command="$MCWRAPPER_CENTRAL/gluex_MC.py MCDispatched.config "+str(RunNumber)+" "+str(NumEventsToProduce)+" per_file=250000 base_file_number="+str(FileNumber_NewJob)+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=0"
        print(command)
        status = subprocess.call(command, shell=True)
    else:
        print "All jobs submitted for this order"

def DispatchToSWIF(ID,order,PERCENT):
    status = subprocess.call("cp $MCWRAPPER_CENTRAL/examples/SWIFShell.config ./MCDispatched.config", shell=True)
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
        command="$MCWRAPPER_CENTRAL/gluex_MC.py MCDispatched.config "+str(RunNumber)+" "+str(NumEventsToProduce)+" per_file=50000 base_file_number="+str(FileNumber_NewJob)+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=2"
        print(command)
        status = subprocess.call(command, shell=True)
    else:
        print "All jobs submitted for this order"


def WritePayloadConfig(order,foundConfig):
    
    MCconfig_file= open("MCDispatched.config","a")
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
    MCconfig_file.write("GENERATOR="+str(order["Generator"])+"\n")
    MCconfig_file.write("GEANT_VERSION="+str(order["GeantVersion"])+"\n")
    MCconfig_file.write("NOSECONDARIES="+str(abs(order["GeantSecondaries"]-1))+"\n")
    MCconfig_file.write("BKG="+str(order["BKG"])+"\n")
    MCconfig_file.write("DATA_OUTPUT_BASE_DIR="+str(order["OutputLocation"])+"\n")
    #print "FOUND CONFIG="+foundConfig
    if foundConfig=="True":
        MCconfig_file.write("GENERATOR_CONFIG="+str(order["Generator_Config"])+"\n")
    else:
        MCconfig_file.write("GENERATOR_CONFIG="+foundConfig+"\n")
    MCconfig_file.write("ENVIRONMENT_FILE=/group/halld/www/halldweb/html/dist/"+str(order["VersionSet"])+"\n")
    MCconfig_file.close()

def DispatchToOSG(ID,order,PERCENT):
    status = subprocess.call("cp $MCWRAPPER_CENTRAL/examples/OSGShell.config ./MCDispatched.config", shell=True)
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

    RequestedEvents_query = "SELECT NumEvents, Is_Dispatched FROM Project WHERE ID="+str(ID)+";"
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
        command="$MCWRAPPER_CENTRAL/gluex_MC.py MCDispatched.config "+str(RunNumber)+" "+str(NumEventsToProduce)+" per_file=20000 base_file_number="+str(FileNumber_NewJob)+" generate="+str(order["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(order["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(order["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(order["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid="+str(ID)+" batch=1"
        print(command)
        status = subprocess.call(command, shell=True)
    else:
        print "All jobs submitted for this order"

def main(argv):
    #print(argv)

    numprocesses_running=subprocess.check_output(["echo `ps all -u tbritton | grep MCDispatcher.py | wc -l`"], shell=True)
    #print(args)
    if(int(numprocesses_running) <6 ):
        ID=-1
        MODE=""
        SYSTEM="NULL"
        PERCENT=1.0
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


        #print MODE
        #print SYSTEM
        #print ID

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
            TestProject(ID)
        elif MODE == "RETRYJOB":
            RetryJob(ID)
        elif MODE == "RETRYJOBS":
            RetryJobsFromProject(ID)
        elif MODE == "CANCELJOB":
            CancelJob(ID)
        elif MODE == "AUTOLAUNCH":
            #print "AUTOLAUNCHING NOW"
            AutoLaunch()
        else:
            print "MODE NOT FOUND"

        
    conn.close()
        

if __name__ == "__main__":
   main(sys.argv[1:])
