#!/usr/bin/python3.6
try:
    import rcdb
except:
    pass
import MySQLdb
import sys
import datetime
import os.path
import time
from optparse import OptionParser
from PIL import Image
import argparse
try:
    import subprocess
    from subprocess import call
    from subprocess import Popen, PIPE
    import socket
    import pprint
    import smtplib                                                                                                                                                                          
    from email.message import EmailMessage
    from multiprocessing import Process, Queue
except:
    pass
import plotly.express as px
import plotly.graph_objs as go
import plotly.figure_factory as ff
import plotly
from plotly.subplots import make_subplots
import pandas as pd


MCWRAPPER_BOT_HOME="/u/group/halld/gluex_MCwrapper/"
dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
curs=conn.cursor(MySQLdb.cursors.DictCursor)

def getAverage(numlist):
    summ=0
    denom=0
    listlen=len(numlist)
    for i in range(0,listlen):
        denom+=numlist[i]
        summ+=i*numlist[i]
    
    if denom != 0:
        print("Avg number of attempts: ", float(summ)/float(denom))
        return float(summ)/float(denom)
    else:
        print("Can't compute Average as it is nan")
        return 0.


def getAttemptDistribution(ID, makePlot,extraConstraint="",outputLoc="./MCAnalyze_out/"):
    print("Getting the distributions of attempts for project",ID)
    count_q="SELECT COUNT(*) as AttemptsCount from Attempts where Job_ID in (SELECT ID from Jobs where Project_ID IN (SELECT ID FROM Project where ID="+str(ID)
    if(extraConstraint != ""):
        count_q+=" && "+extraConstraint
    count_q+=")) GROUP BY Job_ID;"
    
    print(count_q)
    curs.execute(count_q) 
    rows=curs.fetchall()
    print("Obtained",len(rows),"Entries")
    rawarr=[]
    count_arr=[]
    xbins=[]
    maxval=0

    for row in rows:
        if(row["AttemptsCount"] > maxval):
            maxval=row["AttemptsCount"]

    for i in range (0,maxval+1):
        count_arr.append(0)
        xbins.append(i)
    for entry in rows:
        rawarr.append(entry["AttemptsCount"])
        count_arr[entry["AttemptsCount"]]+=1


    if(makePlot):
        df=pd.DataFrame(rawarr,columns=["Attempts_Count"])
        fig = px.histogram(df,x="Attempts_Count",nbins=len(count_arr))
        plotly.offline.plot(fig,filename=outputLoc+"CountDistribution_"+str(ID)+".html",image = 'png', image_filename=outputLoc+"CountDistribution_"+str(ID))
    

    print(count_arr)

    

    return getAverage(count_arr)

def getAttemptFailurePie(ID,extraConstraint="",fileName="failurePie_Total",outputLoc="./MCAnalyze_out/"):
    print("Getting the Failure Pie for project ",ID)
    count_q="SELECT ProgramFailed as pf,COUNT(*) as AttemptsCount from Attempts where Job_ID in (SELECT ID from Jobs where Project_ID IN (SELECT ID FROM Project where ID>"+str(ID)
    if(extraConstraint != ""):
        count_q+=" && "+extraConstraint
    count_q+=")) GROUP BY ProgramFailed;"
    
    print(count_q)
    curs.execute(count_q) 
    rows=curs.fetchall()
    print("Obtained",len(rows),"Entries")
    df=pd.DataFrame(rows)

    titleString="Failure Blame For "
    
    if(int(ID)==0):
        titleString+="All Projects"

    if(extraConstraint != ""):
        titleString+=" passing "+extraConstraint

    titleString+=" ("+ str(df['AttemptsCount'].sum()) +" Attempts) "

    fig = px.pie(df, values='AttemptsCount', names='pf', title=titleString)
    fig.update_traces(textposition='inside', textinfo='percent+label')
    plotly.offline.plot(fig,filename=outputLoc+fileName+".html",image = 'png', image_filename=outputLoc+fileName)

def main(argv):
    ap = argparse.ArgumentParser()

    ap.add_argument("-P", "--projectID", required=True,
    help="The ID number of the project to be analyzed")

    ap.add_argument("-x", "--xaxis", required=False,
    help="the x axis key for the avg attempts per job")

    ap.add_argument("-e", "--extraConstraint", required=False,
    help="an added constraint agains the Project table")

    ap.add_argument("-o", "--outputloc", required=False,
    help="path to the output directory")

    args = vars(ap.parse_args())

    extraConstraint=""

    if(not args["extraConstraint"] is None):
        extraConstraint=args["extraConstraint"]

    outputLoc="./"

    if(not args["outputloc"] is None):
        outputLoc=args["outputloc"]


    outputLoc+="MCAnalyze_out/"

    subprocess.call("mkdir -p "+outputLoc,shell=True)

    ProjectID=args["projectID"]
    Xaxis_key=args["xaxis"]

    if int(ProjectID) != 0:
        print("Analyzing project #",ProjectID)
        getAttemptDistribution(ProjectID,True,outputLoc=outputLoc)
        getAttemptFailurePie(0,"ID="+str(ProjectID),"failurePie_Proj"+str(ProjectID),outputLoc)

    else:
        print("Total analysis")
        weightedAvg_arr=[]
        getAll_q="SELECT * FROM Project WHERE Tested>0 "
        if(extraConstraint != ""):
            getAll_q+=" && "+extraConstraint
        getAll_q+=" Order by ID asc"

        print(getAll_q)
        curs.execute(getAll_q) 
        rows=curs.fetchall()
        Totaldf = pd.DataFrame(rows)
        x_arr=[]
        
        for row in rows:
            if(not row[Xaxis_key]):
                x_arr.append("NA")
            else:
                x_arr.append(row[Xaxis_key])
            weightedAvg_arr.append(getAttemptDistribution(row["ID"],False))
        #print(weightedAvg_arr)
        Totaldf["avg_attempts_per_jobs"]= weightedAvg_arr
        #print("is numeric?",str(x_arr[0]).isnumeric())
        titleString="All Projects Status>0"
        if(extraConstraint != ""):
            titleString="Projects passing "+extraConstraint
        if(str(x_arr[0]).isnumeric() or isinstance(x_arr[0],datetime.datetime)):
            fig = px.scatter(x=x_arr, y=weightedAvg_arr)
            fig.update_layout(yaxis_type="log",xaxis_title=Xaxis_key,yaxis_title="avg_attempts_per_jobs",title=titleString)
            
        else:
            fig = px.histogram(Totaldf,x=Xaxis_key,y="avg_attempts_per_jobs", histfunc='avg')
        
        plotly.offline.plot(fig,filename=outputLoc+"/CountDistribution_Total"+".html",image = 'png', image_filename=outputLoc+"/AvgCountDistribution_Total")

        print("XAxis:",Xaxis_key)
        if("Set" not in Xaxis_key):
            getAttemptFailurePie(ProjectID,extraConstraint,"failurePie_Total",outputLoc)
        else:
            vset_q="SELECT DISTINCT "+Xaxis_key+" FROM Project"
            curs.execute(vset_q) 
            rows=curs.fetchall()
            for row in rows:
                print(row)
                key="NULL"
                if(not row[Xaxis_key] is None):
                    key=row[Xaxis_key]
                print("KEY:",key)
                if key != "NULL":
                    getAttemptFailurePie(ProjectID,Xaxis_key+"=\""+key+"\"","FailurePie_"+key,outputLoc)
                else:
                    getAttemptFailurePie(ProjectID,Xaxis_key+" is "+key,"FailurePie_"+key,outputLoc)


if __name__ == "__main__":
   main(sys.argv[1:])