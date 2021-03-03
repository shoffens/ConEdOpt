# -*- coding: utf-8 -*-
"""
@author: Amineh Zadbood, azadbood@stevens.edu
#Worker availability shown marked on the first column of the table - 6 priority levels - 
# ==============================================================================================================
# This code does sequential optimization to create a weeklong schedule. It reads a csv file comprised of
the work order information. It then solves daily scheduling problems using CPLEX.
** Work orders are referred to as jobs.
** HJ is the HOURS column in the csv file that keeps being updated.
** due denotes the due dates measured in hours. # Zero date is '2020-07-30'. due is calculated by (DueDate - zero date) * 8 (assumingdays are 8-hour long)
# ============================================================================================================
"""
# Import Python libraries
import cplex
import csv
import pandas as pd
import numpy as np
import math
from matplotlib import pyplot as pl
import datetime
import time
import os
from collections import defaultdict
from collections import Counter

# dfall=None
# dfcopy=None
# dfJ = None
# HJ=None
# lowerj=None
# jinJ=None
# hhours=None
# removedrow=None
# var_vals = None
# Mx = None
# scheduledJ = None
# scheduledj = None

#Use this to get the execution time
start_time = time.time()

#%% ****************** Read in CSV files ***********************************

# Read the csv file and save it as a data framenamed "df" ; "converters" helps to keep leading zeros when opening a csv file using Pandas
df = pd.read_csv("input_work_orders.csv",encoding = 'unicode_escape',converters={'WONUM': lambda x: str(x)})    
#Read worker schedule_calendar ; "converters" helps to keep leading zeros when opening a csv file using Pandas
dfcal = pd.read_csv("input_employee_schedule.csv",encoding = 'unicode_escape', converters={'EMPLOYEE_ID': lambda x: str(x)})
#Read the data which shows which week we are planning for - It has one value - the date of Sunday
dfweek = pd.read_csv("input_parameters.csv",encoding = 'unicode_escape')
#Matrix of employees and profienicies (1-5 skill level)
proficiency = pd.read_csv("input_employee_info.csv",converters={'EMPLOYEE_ID': lambda x: str(x)})
#Read 2020 dates
# dfn = pd.read_csv("2021cal.csv",encoding = 'unicode_escape')
#On this file task names are associated with a task key
taskkey = pd.read_csv("input_proficiency_master.csv")

# Delete daily .csv files (otherwise they will keep appending):
if os.path.isfile('dailyoutputcsv.csv'):
    os.remove('dailyoutputcsv.csv')

#%% NEW approach to calendar information:
dayrange = 28       # Number of days into the future to consider
sundate = list(dfweek.Value)
calendar = [pd.to_datetime(sundate) + datetime.timedelta(days=x) for x in range(dayrange)]

# Create list of weekdays/workdays:
workdaycal = []
for i in range(dayrange):
    if (calendar[i].strftime("%A")[0] != 'Sunday') & (calendar[i].strftime("%A")[0] != 'Saturday'):
        workdaycal.append(calendar[i].strftime("%Y-%m-%d")[0])
        
#%% Remove lower-priority, 8-hour jobs that well exceed 2x the scheduling capacity
bufferfactor = 5           # Can make this 3x or something else
df_original = df

# Delete rows with hours or crewz = 0:
df = df[df.CREW_SIZE != 0]
df = df[df.HOURS != 0]

# Remove all jobs that are not E-Plan status = READY or Maximo status = APPR or REWORK
# df = df[(df.EPLAN_STATUS == 'READY') & (df.MAXIMO_STATUS == 'APPR')]

# Remove problematic jobs (found by trial and error)
# df = pd.concat([df[:1718],df[1719:]])

# Remove priority-4 jobs that are not due in the next three weeks:
duedates = pd.to_datetime(df.DUE_DATE)
fixeddates = pd.to_datetime(df.FIXED_DATE)
df.insert(10,'duedates',duedates)
df.insert(11,'fixeddates',fixeddates)
startdate = dfweek.Value[0]
mondate = pd.to_datetime(startdate) + pd.DateOffset(days=1)
enddate = pd.to_datetime(startdate) + pd.DateOffset(days=21)
endfixeddate = pd.to_datetime(startdate) + pd.DateOffset(days=5)
pre_fixedjobs = df[(df.fixeddates <= endfixeddate) & (df.fixeddates >= pd.to_datetime(mondate))]
df = pd.concat([df[(df.PRIORITY != 4)], df[(df.duedates <= enddate) & (df.duedates >= mondate)]])

# Remove OUTAGE jobs that are not fixed to occur this week:
df_o = df[df.OUTAGE_REQUIRED == True]   # Identify outage-required jobs
df_os = pd.DataFrame(columns = df.columns)  # Create df of outage-required jobs with fixed dates
for i in range(5):
    fdate = workdaycal[i]
    df_os = df_os.append(df_o[df_o.FIXED_DATE == fdate])  # Identify those that are scheduled this week
df = pd.concat([df[df.OUTAGE_REQUIRED != True],df_os])

# Now, remove the priority-5 and priority-6 jobs and add them back:
df_6 = df[(df.PRIORITY == 6) & (df.HOURS == 8)]
df_not6 = pd.concat([df[df.PRIORITY !=6], df[(df.PRIORITY == 6) & (df.HOURS != 8)]])
df_5 = df[(df.PRIORITY == 5) & (df.HOURS == 8)]
df_not56 = pd.concat([df_not6[df_not6.PRIORITY !=5], df_not6[(df_not6.PRIORITY == 5) & (df_not6.HOURS != 8)]])
totalwhours = 40*len(proficiency)               # Number of worker-hours potentially available
totalhours = df['PLAN_HOURS'].sum()               # Number of hours in original schedule
totalhours_excl6 = df_not6['PLAN_HOURS'].sum()
totalhours_excl56 = df_not56['PLAN_HOURS'].sum()  # Number of hours if all 5's removed
if totalhours > totalwhours*bufferfactor:                  # If backlog has more than 3x available worker hours...
    if totalhours_excl6 >= totalwhours*bufferfactor:        # If backlog after removing 6's is still too big...
        df = df_not6
    if totalhours_excl56 >= totalwhours*bufferfactor:        # If backlog after removing 5's still does...
        df = df_not56
    else:                                       # Find percentage of P5 jobs to return
        hourstoaddback = (totalwhours*bufferfactor - totalhours_excl56)/(totalhours - totalhours_excl56)
        df_5add = df_5[:math.ceil(hourstoaddback*len(df_5))]
        df = pd.concat([df_not56,df_5add])
        
# Now, let's check and see if any fixeddates jobs were removed:
reduced_fixedjobs = df[df.fixeddates <= endfixeddate]
if len(pre_fixedjobs) > len(reduced_fixedjobs):
    listreduced = list(reduced_fixedjobs.index)
    listtoaddback = pd.DataFrame(columns = df.columns)
    for i in pre_fixedjobs.index:
        if i not in listreduced:
            listtoaddback = listtoaddback.append(pre_fixedjobs[pre_fixedjobs.index == i])
    df = pd.concat([df,listtoaddback])     
        
# Renumber the indices in the dataframe df        
df = df.reset_index(drop=True)
    
#%%############################ PREPROCESSING INPUT FILES ###############################################################
#In these cases, we want to optimize the job into the schedule (most likely we are going to predetermine the date to work as this circumstance is usually outage related) as if the job is only planned for 8 hours/day.
##### Set 8+ hour/day jobs to 8 hours:
df.loc[df['HOURS'] > 8 , 'HOURS'] = 8

# In the "input_employee_info.csv" file received on July 30, worker ID's do not have leading zeros.
# Add leading zeros to make ID's read from here and the resource calendar consistent
for i in range(2,len(proficiency.index)):
    #Add leading zeros to have 5 digits (operator: dot z fill (5))
    if len(proficiency["EMPLOYEE_ID"][i]) < 5: #normally ID's are 5 digits
        proficiency["EMPLOYEE_ID"][i] = proficiency["EMPLOYEE_ID"][i].zfill(5)
#Empty cells in the proficiency file are replaced with level '1'.
proficiency = proficiency.fillna('1')
dfcopy=df.copy()
#Add a column to the dataframe to keep track of workers of multishift jobs
dfcopy['wtocont'] = [[] for _ in range(dfcopy.shape[0])]

################## Find unique work order numbers for J ############################
jobnum = list(df.WONUM)
jobnum_uq = []
for i in jobnum:
    if i not in jobnum_uq:
        jobnum_uq.append(i) 
numJ = len(jobnum_uq) 
#%% This may be obsolete since Endevor started pre-splitting jobs? ####
# # Create a dictionary to associate a job number (J; starting from 0) to every unique WONUM
# presplitJ = list(range(len(jobnum_uq)))
# #keys = jobnum_uq
# #values = J = 0, ..., len(jobnum_uq) - 1
# jobdict_J_WONUM = {jobnum_uq[i]: presplitJ[i] for i in range(len(jobnum_uq))}
# profecy_colnames = list(proficiency.columns)
#%% ########################## Process worker data #####################################
# dfcal: worker schedule csv read as a dataframe
# save EMPLOYEE_ID column from employee schedule as a list
worker_ID_5dig = dfcal['EMPLOYEE_ID'].tolist()     
# remove duplicates in the employee id list (each worker comes in more than one row)
worker_ID_5dig_Uq = []
for i in worker_ID_5dig:
    if i not in worker_ID_5dig_Uq:
        worker_ID_5dig_Uq.append(i) 
#Associate range(numw) with worker ID’s
#Bronx employee numbers start from 0 to len(WoID_5dig_Uq)
worker_no=list(range(len(worker_ID_5dig_Uq))) #0 ... 9
#Convert employee number and employee id lists into a dictionary using dictionary comprehension
# initializing lists
#keys = worker_ID_5dig_Uq
#values = worker_no = 0, ..., 9
#Use dictionary comprehension to convert lists to dictionary
dictworker_id_no = {worker_ID_5dig_Uq[i]: worker_no[i] for i in range(len(worker_ID_5dig_Uq))}
#Create a list from proficiency file employee_id
#Add workernumber column to proficiency dataframe
worker_ID_temp = proficiency['EMPLOYEE_ID'].tolist()  
tempwno = []
#worker number is an integer starting from 0 that is added as a new column to the dataframe
for i in range(len(worker_ID_temp)):
    if len(worker_ID_temp[i]) == 0: #empty
        tempwno.append("")
    else:
        tempwno.append(dictworker_id_no[worker_ID_temp[i]]) 
proficiency = proficiency.assign(workernumber = tempwno) 

#Add workernumber column to input_employee_schedule/Bronx
tempwnosch = []
for i in range(len(worker_ID_5dig)):
    tempwnosch.append(dictworker_id_no[worker_ID_5dig[i]]) 
dfcal = dfcal.assign(workernumber = tempwnosch) 

#%% ######################### worker availability preprocessing ################# dataframe:newdfcalw_bss ####################
#Filter the dataframe to "Shift 2: 7am-3:30pm" only
#Save the date of work days in the 2020 calendar as a list
dfcalw = dfcal.loc[dfcal['SHIFT_DESC'] == "Shift 2: 7am-3:30pm"]  #Bronx
dfcalw.reset_index(drop=True, inplace=True)
## convert your datetime into pandas
dfcalw.SCHEDULE_DATE=pd.to_datetime(dfcalw.SCHEDULE_DATE)
#Remove weekends from resource calendar test
res_cal_dates = dfcalw['SCHEDULE_DATE'].to_list()

#%% ############## Preprocessing calendar information (OBSOLETE) ##############
# # convert datetime into pandas
# dfn.date=pd.to_datetime(dfn.date)
# day_exclusion = ['Saturday', 'Sunday']
# # Remove weekends 
# dfnoss=dfn[~(pd.to_datetime(dfn['date']).dt.day_name().isin(day_exclusion))]
# #reset index
# dfnoss.reset_index(drop=True, inplace=True)

# #Start of the week (Sunday)
# sundate = list(dfweek.Value)
# #Add a column to the dataframe to do some operations on the date
# dfweek["weeksun"] = sundate
# #convert string to datetime
# dfweek["weeksun"] = pd.to_datetime(dfweek["weeksun"], dayfirst = True)
    
# #Create a list from the 2020 dates -the year 2020 business days
# twenty_bss_dates = dfn['date'].to_list()
# #Convert the timestamp object to dataframe
# for i in range(len(twenty_bss_dates)):
#     if str(twenty_bss_dates[i]) != 'NaT':
#         twenty_bss_dates[i] = twenty_bss_dates[i].strftime('%Y-%m-%d')
        
# for i in range(len(res_cal_dates)):
#     if str(res_cal_dates[i]) != 'NaT':
#         res_cal_dates[i] = res_cal_dates[i].strftime('%Y-%m-%d')

#%% NEW approach to calendar information:
# # This part was moved up so it could be used in the filtering steps:
# dayrange = 28       # Number of days into the future to consider
# sundate = list(dfweek.Value)
# calendar = [pd.to_datetime(sundate) + datetime.timedelta(days=x) for x in range(dayrange)]

# # Create list of weekdays/workdays:
# workdaycal = []
# for i in range(dayrange):
#     if (calendar[i].strftime("%A")[0] != 'Sunday') & (calendar[i].strftime("%A")[0] != 'Saturday'):
#         workdaycal.append(calendar[i].strftime("%Y-%m-%d")[0])

# Create list of dates on resource calendar (worker availability):        
for i in range(len(res_cal_dates)):
    if str(res_cal_dates[i]) != 'NaT':
        res_cal_dates[i] = res_cal_dates[i].strftime('%Y-%m-%d')

#%%**************** number of workers and number of hours **************
numw = len(worker_ID_5dig_Uq)  
numt = 8 
# At a maximum, how many seconds do you want the code that creates the daily schedule takes to run?
runtime = 3600 #1 hours
day = 1

#%% Daily optimization loop
def dailyoptimization():
    global dfall    # Database of jobs. Unclear how different from df
    global dfcopy   # Same as dfall. Unclear why it exists
    global dfJ      # dataframe of J groups (jobs with same WONUM)
    global HJ       # hours left in J groups
    global lowerj
    global jinJ
    global hhours
    global removedrow
    global var_vals
    global Mx
    global scheduledJ
    global scheduledj
# "df" is the original dataframe that was created when the CSV file was read in the program named "SequentialOpt_Weeklyschedule.py"
# "dfall" post-split jobs - Basically that is df but some rows are deleted for some purposes
# "dfJ" multiple shifts (j) of a job with the same work order number all combined and are known as one J job

    #%%###### pre-split jobs: j that will be later combined into J ############################# 
    #Create a copy of the dataframe with all j’s / rows / jobs before grouping
    dfall = dfcopy.copy()
    # Task
    dfall["TASK"] = dfall["PROFICIENCY_NBRS"]
    ##Deal with more than one required task for a job
    for i in range(len(dfall.index)):
        if "|" in dfall["PROFICIENCY_NBRS"][i]:
            # pipe delimited values saved as a string
          dfall.iloc[i, dfall.columns.values.tolist().index("TASK")] = "59"
      
    cols_of_interest = ['WONUM','REPORT_DATE','DUE_DATE','FIXED_DATE','NUMBER_OF_DAYS','DAY_NUMBER','CREW_SIZE','HOURS','PRIORITY','OUTAGE_REQUIRED','OUTAGE_START','OUTAGE_END','DOWNTIME','PROFICIENCY_NBRS','TASK','wtocont']
    #Limit columns of the dataframe to the ones needed
    dfall = dfall[cols_of_interest]
    
    #%% ######### Manage date columns ######################################################
    firstday = list(dfweek.Value)
    target_week = firstday[0]
    target_weekZ = pd.to_datetime(target_week)
    
    #Save theDue Date column in the csv in this list 
    duedate = list(dfall.DUE_DATE)
    #Add a column to the dataframe to do some operations on the due dates
    dfall["DUE"] = duedate
    #convert string to datetime
    dfall["DUE"] = pd.to_datetime(dfall["DUE"], dayfirst = True)
    #Replace WhiteSpace with a 0 in Pandas (Python 3)
    dfall['DUE'] = dfall['DUE'].apply(lambda x: 0 if x == ' ' else x)
    
    ##################### DUE DATES ###############################
    #Calculate the due dates that will be used in the objective function
    # The number of days between the date on the Due Date column of the csv file and the target_week date specified as 1/1/2019
    dfall["DUEDUE"] = (dfall["DUE"] - target_weekZ).dt.days
    
#%% ########### Identify dates of the week (NEW) ########### 
    # Identify weekend rows of resource calendar
    weekendrows=[i for i, item in enumerate(res_cal_dates) if item not in workdaycal]
    #Delete weekeds from resource calendar dataframe
    dfcalw_bss = dfcalw.drop(dfcalw.index[weekendrows])
    #reset index and save it as a column
    dfcalw_bss.reset_index(drop=True, inplace=True)

    # Create an index of business day working hours:       
    bushours = []
    for i in res_cal_dates:
        if i in workdaycal:
            bushours.append(workdaycal.index(i) + 1)
            
    #daynumber = [item for item in bushours]
    dfcalw_bss["dayN"] = bushours
    daydate = workdaycal[day - 1]
    
    ##### NOT SURE IF THE NEXT FEW LINES ARE REALLY NEEDED:
    #Copy the dataframe
    newdfcalw_bss = dfcalw_bss.copy()
    #Repeat each row 8 times (8 hours per day)
    newdfcalw_bss = newdfcalw_bss.loc[np.repeat(newdfcalw_bss.index.values, 8)]
    #reset index
    newdfcalw_bss.reset_index(drop=True, inplace=True)
    
#%% ########### IDENTIFY DATES OF THE WEEK (OBSOLETE) ###############         
            
    # firstddate_sun = dfweek["weeksun"].to_list()
    # for i in range(len(firstddate_sun)):
    #     if str(firstddate_sun[i]) != 'NaT':
    #         firstddate_sun[i] = firstddate_sun[i].strftime('%Y-%m-%d')
            
    # # delweekendsIDX = []
    # #Find indices of elements in one list that are not in the other list
    # weekendsrows=[i for i, item in enumerate(res_cal_dates) if item not in twenty_bss_dates]

    # #Delete weekeds from resource calendar dataframe
    # dfcalw_bss = dfcalw.drop(dfcalw.index[weekendsrows])
    # #reset index and save it as a column
    # dfcalw_bss.reset_index(drop=True, inplace=True)
    
    # #Add a "working hours" column starting from hour 1 on 7/6/2020 to the datfatcalw_bss
    # bzzhours = []
    # for i in res_cal_dates:
    #     if i in twenty_bss_dates:
    #         bzzhours.append(twenty_bss_dates.index(i) + 1)
    
    # #Find the first week start date (Sunday) in the 2020 cal
    # year2020dates = dfn['date'].to_list()
    # #Convert the timestamp object to dataframe
    # for i in range(len(year2020dates)):
    #     year2020dates[i] = year2020dates[i].strftime('%Y-%m-%d')
    # first_sun_index = year2020dates.index(firstddate_sun[0])
    # #The date of the first Monday of the week to be planned 
    # firstMondate = year2020dates[first_sun_index+1]
    # daydate = year2020dates[first_sun_index+day]
    # firstMon = twenty_bss_dates.index(firstMondate) + 1
    
    # dfcalw_bss["dayoftheyear"]=bzzhours
    
    # #Add a new column dayno - assume the first working day of the week we are planning for = day 1!!
    # dayno = dfcalw_bss['dayoftheyear'].to_list()
    # #Find the first Monday of the week we are planning for is which day of the year 2020
    # firstMon = firstMon - 1
    # #val - firstMon 
    # daynumber = [item - firstMon for item in dayno]
    # dfcalw_bss["dayN"] = daynumber
    # #Column hours shows how many hours the person works
    
    # #Copy the dataframe
    # newdfcalw_bss = dfcalw_bss.copy()
    # #Repeat each row 8 times (8 hours per day)
    # #repts = [val for val in 9]
    # newdfcalw_bss = newdfcalw_bss.loc[np.repeat(newdfcalw_bss.index.values, 8)]
    # #reset index
    # newdfcalw_bss.reset_index(drop=True, inplace=True)
    
#%%#################Preprocess jobs based on outage requirement###################################
    # Outage dates
    #Remove jobs that their outage duration is not coming
    removedrow= []
    #If a subjob in J is due today, keep all the other subjobs to be continued on secutive days
    ###****************************** outage columns ****************

    # Get information about outages:
    outage_st = list(pd.to_datetime(dfall.OUTAGE_START))
    fixed = list(pd.to_datetime(dfall.FIXED_DATE))
    downT = list(dfall.DOWNTIME)
    #Convert the timestamp object to dataframe
    for i in range(len(fixed)):
        if str(fixed[i]) != 'NaT':
            fixed[i] = fixed[i].strftime('%Y-%m-%d')
    
    #Keep track of J of outage required jobs due today, to keep all its sub-jobs in the dataframe
    WONUMin = [] 
    for j in range(len(dfall)):
        if downT[j] == 1 and str(outage_st[j]) != 'NaT' :
            #If daydate!= fixeddate then remove job j from the data frame just for that day before the optimization starts
            if fixed[j] == daydate :
                #All the subjobs of this J have to stay
                WONUMin.append(dfall.iloc[j]["WONUM"])   
    
    #Check jobs on df2 and save the indices if the outage is not due to remove these rows later
    indexdel = [] 
    for j in range(len(dfall)):
        if downT[j] == 1 and str(outage_st[j]) != 'NaT' :
            #If daydate!= fixeddate then remove job j from the data frame just for that day before the optimization starts
            if fixed[j] != daydate and dfall.iloc[j]["WONUM"] not in WONUMin:
                #Keep a list of indexes that has to be later removed (and none of its j's is due today)
                  indexdel.append(j)
    #Add the rows that should be removed to a list
    for i in indexdel:
        removedrow.append(dfall.iloc[[i]])
    
    #Remove jobs from df
    dfall = dfall.drop(dfall.index[indexdel])
    dfall.reset_index(drop=True, inplace=True)

    #df got updated, so the lists should be updated as well!
    outage_st = list(pd.to_datetime(dfall.OUTAGE_START))
    fixed = list(pd.to_datetime(dfall.FIXED_DATE))
    downT = list(dfall.DOWNTIME)
    #Convert the timestamp object to dataframe
    for i in range(len(fixed)):
        if str(fixed[i]) != 'NaT':
            fixed[i] = fixed[i].strftime('%Y-%m-%d') 
#%%*********** Get hours, crew size columns before grouping ****************
    #hhours is the hour of pre-grouping jobs #post-split jobs
    hhours = list(dfall.HOURS)
    hhours = [ int(x) for x in hhours ]
    ccrewz = list(dfall.CREW_SIZE)
    #Priority of the pre-combined jobs
    priority = list(dfall.PRIORITY)
    
    # convert index of a column into a column
    dfall['index1'] = dfall.index
    #renumbered list of jobs; lowerj
    lowerj =dfall['index1'].tolist()
    
    q = list(dfall.TASK) # q stands for qualification
    
    q = [float(x) for x in q]
    #Replace nan with zero
    q = [0 if math.isnan(i) else i for i in q] 
    #Call int() function on every list element?
    q = [ int(x) for x in q ]# -*- coding: utf-8 -*-   
#%% Groupby cannot handle NAN values - first replace nans in the DUE_DATE & FIXED_DATE column with zero
    dfall["DUE_DATE"].fillna(0, inplace = True)
    dfall["FIXED_DATE"].fillna(0, inplace = True)           
    # Group by WONUM and NUMBER_OF_DAYS means put all those with the same values for both WONUM and NUMBER_OF_DAYS in the one group
    # Identify the columns we want to aggregate by
    dfJ = dfall.copy()
    group_cols = ['WONUM','NUMBER_OF_DAYS']
    
    # Identify the columns which we want to sum
    metric_cols = ['HOURS']
    
    # create a new DataFrame with a MultiIndex consisting of the group_cols and a column for the mean of each column in metric_cols
    aggs = dfJ.groupby(group_cols)[metric_cols].sum()
    # remove the metric_cols from df because we are going to replace them with the means in aggs
    dfJ.drop(metric_cols, axis=1, inplace=True)
    # dedupe to leave only one row with each combination of group_cols
    # in df
    dfJ.drop_duplicates(subset=group_cols, keep='last', inplace=True)
    # add the mean columns from aggs into df
    dfJ = dfJ.merge(right=aggs, right_index=True, left_on=group_cols, how='right')
    
    #Turn ZERO values in DUE_DATE & FIXED_DATE columns into empty cells
    date_target_week_df = dfJ.astype(str)
    date_target_week_df['DUE_DATE'].replace(['0', '0.0'], '', inplace=True)
    date_target_week_df['FIXED_DATE'].replace(['0', '0.0'], '', inplace=True)
    
    dfJ = date_target_week_df.copy()
    
    #reset the index
    dfJ.reset_index(drop=True, inplace=True)
    
    #Original job numbers : Job numbers are integers ranging from 0 to the number of jobs - 1.
    #The dataframe index is used as job numbers.
    dfJ['ORGjobno'] = dfJ.index
    #Get a list from dataframe colum
    ORG_jobno = dfJ['ORGjobno'].tolist()
    
    #Add this column of J to the dataframe with multiple j's with the same J (dfall)
    ORG_jobnoall=[]
    for i in range(len(dfall)):
            #Assuming WONUM'a are unique
        indexW = dfJ["WONUM"].tolist().index(dfall.iloc[i]["WONUM"])
        ORG_jobnoall.append(dfJ.iloc[indexW ]["ORGjobno"])
        # ORG_jobnoall.append(dfJ.iloc[indexW, 19])
    dfall['ORGjobno'] = ORG_jobnoall
    
#%%#################### Save columns in the combined dfJ ################
    # Jobs
    jobnum = list(dfJ.WONUM)
    numJ = len(jobnum) 
    # Hours of the pre-split jobs
    hours_float = list(dfJ.HOURS)
    #Call int() function on every list element
    HJ = [ int(float(x)) for x in hours_float ]
    
    #Priority of the pre-combined jobs
    pJ = list(dfJ.PRIORITY)
    pJ = [ int(x) for x in pJ]
    
    # Crew size of the pre-split jobs
    CJ = list(dfJ.CREW_SIZE)
    CJ = [ int(x) for x in CJ]
    
    #DUE_DATE column 
    due = list(dfJ.DUEDUE)
    # day * hour = time
    for i in range(len(due)):
        #make all sstring numbers integer
        if due[i] != 'nan':
            due[i] = int(float(due[i]))
        if due[i] != 'nan' and due[i] > 0:
            due[i] = due[i] * 8
        if due[i] != 'nan' and due[i] < 0:
             due[i] = 80
         #Find and replace 'nan' with a number
        if due[i] == 'nan':
            due[i] = 0
         
#%%################### jinJ#######################
    
    #Add single shift jobs to lowerj
    jinJ = [] #[[0],[1],[2],[3],[4],[5,6],[7],...]
    #Find the indices of duplicates in ORGjobno in dfall
    # def index(arr, num):
    sameJ = []
    # for k in ORG_jobno:
    for k in ORG_jobno:
        for i, x in enumerate(ORG_jobnoall):
            if x == k:
                sameJ.append(i)
        jinJ.append(sameJ)
        sameJ = []
               
    #%% Access t in e_wt (from the tindex column in the newdfcalw_bss datafram)
    # Working Hours 1 to 8 added as a list
    L = []
    for io in range(len(dfcalw_bss)):
        for jo in range(1,9):
            L.append(jo)
            
    # Add hours to the dataframe
    newdfcalw_bss["whour"] = L
    myhours = []
    for h in range(len(L)):
        myhours.append((newdfcalw_bss['dayN'].to_list()[h] - 1) * 8 + L[h])
        
    newdfcalw_bss["tindex"] = myhours
    
#%% Access w in e_wt
    #Add a column to the dataframe which shows wgqker number: (based on the list in the "Proficiencies SSO rev 3" w=0 is Acosta, w=1 Brown, w=2 Erigo ,...
    #Worker numbers on windex column start from 1 (not 0) WHY?
    newdfcalw_bss["windex"] = list(newdfcalw_bss.workernumber)
    orgq = list(dfJ.TASK) # q stands for qualification
    orgq = [ int(x) for x in orgq ]
    
    ################## pre-split jobs: J ############################
    #%% Parameter Ew: how many hours this worker continues to be available beyond today
    #Save colmns in the newdfcalw_bss dataframe as lists
    time_cal = list(newdfcalw_bss.tindex)
    avail_cal = list(newdfcalw_bss.AVAILABILITY_TYPE)
    
    Ew = []
    for w in range(numw):
        #Filter to rows with w in windex
        w_cal_df = newdfcalw_bss.loc[newdfcalw_bss['windex'] == w] 
        w_cal_df.reset_index(drop=True, inplace=True)
        time_cal = list(w_cal_df.tindex)  
        avail_cal = list(w_cal_df.AVAILABILITY_TYPE)  
        #Availability for consecutive hours- including today 
        presence = 0  
        initialt = (day-1) * 8 + 1 ##including today (day-1) * 8
        if initialt in time_cal:
            if avail_cal[time_cal.index(initialt)] == 'Standard':
                presence = 1
                while initialt + 1 < 40 + 1 and initialt+1 in time_cal:  #40:one week
    
    
                    if avail_cal[time_cal.index(initialt + 1)] == 'Standard':
                        presence += 1
                    initialt = initialt + 1
        
        Ew.append(presence)
    
#%% number of shifts (8-hour blocks)
    numb = numt // 8
    
    # #Decision variables     #Xjwt                  #Zjt                    #tJ   #aj       #yJ    #Ijt              +deltajw
    num_decision_var = len(lowerj) * numw * numt + len(lowerj) * numt + numJ+ len(lowerj) + numJ + len(lowerj) * numt + len(lowerj)* numw
    
    #  *********************** Proficiencies ***********************************
    # tasklabel = taskkey['Proficiency_Desc'].tolist()
    # taskno = taskkey['Profienency_Nbr'].tolist()
    
    #%% ######## Functions for Proficiencies############################################
    def workerskill(wno, qno):
        taskprof = list(proficiency[qno])
        whichworker = list(proficiency.workernumber)
        s = taskprof[whichworker.index(wno)]
        return taskprof,s
    
    def Cws(qno, wk):
        #return the Cws = the level of proficiency of worker w for job j which needs task qj
        return workerskill(wk, qno)[1]
    
    def qualifiedw(qno, l):
        # Count the number of workers whose Cws = l
        neww = []
        for ww in range(numw):
            #if Cws is l, add that worker index to a list
            if Cws(qno, ww) == str(l):
                neww.append(ww)
        return neww      
                     
#%% *********************** Functions ***********************************
    # Calculate the cofficient in the objective function
    def tenpower(j):
        #h_j * n_j * 10^(6-p_j)
        return HJ[j] * CJ[j] * 10 ** (6 - pJ[j])
    
    # Convert all the elements of a matrix into integer type3600
    def convert_to_int(R):
        for i in range(len(R)):
            for j in range(len(R[i])):
                for k in range(len(R[i][j])):
                    R[i][j][k] = int(R[i][j][k])
        return R
        
#%%    Find the location of each index among the decision variables
    def getzindex(j,t,T):
        # variables are : Xjwt, Zjt, tj
        return (t + (j - 1) * T) + len(lowerj)*numw*numt -1
    
    def getxindex(j,w,t,W,T):
        return (t + (w - 1) * T + (j - 1) * W * T) - 1
    
    def gettindex(jj,numJ,numw,numt):
        return jj  + len(lowerj)*numw*numt  + len(lowerj)*numt - 1

    #aj: if job j is scheduled for the week , 0  otherwise    
    def getaindex(aj,nonumJ,numw,numt):
        return aj  + len(lowerj)*numw*numt  + len(lowerj)*numt + numJ  - 1

    #yJ:  if all subjobs in J have been scheduled , 0 otherwise
    def getyindex(yJ,nonumJ,numw,numt):
        return yJ  + len(lowerj)*numw*numt  + len(lowerj)*numt + numJ + len(lowerj) - 1

    #IJt
    def getIjtindex(Ijt,t,numw,numt):
        return (t + (Ijt - 1) * numt)  + len(lowerj)*numw*numt  + len(lowerj)*numt + numJ + len(lowerj) + numJ - 1
    
    #delta_jw
    def getdeltajwindex(delt,w,numw,numt):  
        return (w + (delt - 1) * numw)  + len(lowerj)*numw*numt  + len(lowerj)*numt + numJ + len(lowerj) + numJ + len(lowerj) * numt - 1
    
    #%%
    # having a number as an index, find its numJ, numw, and numt
    def findjwt(sol):
        cntr = -1
        assgt = []
        for jj in range(1, len(lowerj) + 1):
            for ww in range(1, numw + 1):
                
                for tt in range(1, numt + 1):
                    cntr += 1
                    assgt.append([])
                    assgt[cntr].append(jj)
                    assgt[cntr].append(ww)
                    assgt[cntr].append(tt)
        return assgt
    
#%% Ensure the left hand side matrix does not have duplicates (Cplex requirement)
    def removedupl(indices, coeff):
      final = defaultdict(int)
      n = len(indices)
      for i in range(n):
        final[indices[i]] += coeff[i]
    
      return list(final.keys()), list(final.values())
    
#%% Functions for drawing table plots
    def workercolor(j,w,t):
        #The updated dataframe job numbers
        colorlist = ['darkorchid','deeppink','red','darkorange','seagreen']
        dfalltask =list(dfall.TASK)
        wcolor = colorlist[int(Cws(dfalltask[j], w-1))-1]
        the_table._cells[(w,t)]._text.set_color(wcolor)

    #%% The output table is drawn using this function. The numbers in the cells show job number J (numbers starting from 1). Column ORGjobno in dfall stores J-1 (numbers start from zero).
    def matrix2table(numt,numw,vas, solo):
        # df2['gammas'] = gam
        # gamma = list(dfJ.ORGjobno)
        gamma = list(dfall.ORGjobno)
        cellval = []
        global Matrix
        Matrix = [[0 for x in range(numt + 1)] for y in range(numw + 1)]
        priotrack = [[0 for x in range(numt + 1)] for y in range(numw + 1)]
        for i in range(1, len(Matrix)):
            Matrix[i][0] = i
            cellval.append( i)
            priotrack[i][0] = 0 #arbitrary
        for u in range(1, len(Matrix[i])):
            Matrix[0][u] = u 
            cellval.append(u)
            priotrack[0][u] = 0
        lowerj = dfall['index1'].tolist()
        lowerjplus = [ x + 1 for x in lowerj ]  
        for i in range(len(vas)):   #solo[i][0] = j* (starting from 1) #solo[i][0]-1 = job number starting from 0
            if vas[i] == 1:
                #gamma + 1 since gamma starts from 0
                Matrix[solo[i][1]][solo[i][2]] = dfall.iloc[solo[i][0] - 1]["WONUM"]    #Why plus 1: since jobs on the lowerj list (post split) start from 0
                cellval.append(gamma[lowerjplus.index(solo[i][0])]+ 1)    #solo[i][0]-1 = job number starting from 0; +1 means the table should show job num starting from 1
                priotrack[solo[i][1]][solo[i][2]] =  priority[solo[i][0]-1]  
        Matrix[0][0] = "W\T"
    
        sch = []
        schj = []
        for i in range(len(vas)):
            if vas[i] == 1.0 or vas[i] == 1:   #Xjwt = 1
                ### WONUM = job id = jobnum [j]
                schj.append(solo[i][0]) #scheduled jobs
                sch.append(gamma[lowerjplus.index(solo[i][0])]+ 1) #scheduled jobs
             
    #    remove duplicate
        resJ = []
        for i in schj:
            if i not in resJ:
                resJ.append(i)      
        notsch = []
        allj = list(range(len(lowerj)))
        
        joe = [x+1 for x in allj]
        for i in joe:
            if i not in resJ:
                notsch.append(i)
        return Matrix, priotrack
     
#%% Create constraints
    def createLRHS():
        ################### Constraint 20######################################################
        #To fix the conflicting issue of constraints 18 and 19
        delx = []
        leftdelx= []
        # delxRHS = []
        dej = -1   
        for j in lowerj:                   
            for w in range(numw):
                for t in range(numt):
                    delx .append([])
                    leftdelx .append([])
                    dej += 1
                    #Left hand sidefor w in qualifiedw(str(q[j]), 1):
                    delx [dej].append(getxindex(j+1,w+1,t+1,numw,numt))
                    leftdelx [dej].append(-1)
                    delx [dej].append(getdeltajwindex(j+1,w+1,numw,numt))
                    leftdelx [dej].append(1)
    
        ############### Constraint 19 - Outage ###################
        #For every j that requires outage ()
        outj = []
        leftoutj= []
        rightoutj = []
        oj = -1 
        # countoutreq = -1
        for j in lowerj:
            # If the Outage required field is checked on
            if downT[j] == 1 and str(outage_st[j])!= 'nan'  :
                if fixed[j] == daydate :
            # if outage_req[j] == 'True' and not pd.isna(float(outage_st[j]))  :
                # print("harhar",j)
                    outj.append([])
                    leftoutj.append([])
                    oj += 1
                    for t in range(hhours[j]):
                        if t < numt:
                            outj[oj].append(getIjtindex(j+1,t+1,numw,numt))
                            leftoutj[oj].append(1)
                    rightoutj.append(0.75*hhours[j])
        # print("outj",outj)
    
        ########### Job continuity 18 ######################3
        contind = []
        leftcontind= []
        cono = -1
        #This ensures that this constraint is only built if day > 1
        if day >1:
            #Each J which started the previous day
            for i in range(len(unfinWONUM)):
                #Find the first occurence of the WONUM of this job - keep this j
                j = dfall["WONUM"].tolist().index(unfinWONUM[i])
                #collect w's
                thesew = []
                #Find the duplicates to know WHO did it ALL the previous days
                WhoAllPrev = np.concatenate(dfall.at[j, 'wtocont'])
                # for wp in [item for item, count in collections.Counter(list(WhoAllPrev)).items() if count > 1]
                if day < 3:
                    for wp in assignedw[i]:
                    #if deltajw_yesterday == 1:
                        for i in range(len(Alljwdelta1)):
                            #find in which list this WONUM exists
                            if unfinWONUM[i] and wp in Alljwdelta1[i]:
                                #deltajw_yest = 1
                                #check proficiency level to be greater than 3
                                if int(workerskill(wp,str(q[j]))[1]) >= 3:
                                     thesew.append(wp)
                    # print("thesew",thesew)
                    if len(thesew) > 0:
                        cono += 1
                        contind.append([])
                        leftcontind.append([])
                        for w in thesew:
                            contind[cono].append(getxindex(j+1,w+1 ,1,numw,numt))
                            leftcontind[cono].append(1) 
                    # countit = 2
                if day > 2:
                    # g = The workers who appear in the list more than once, meaning they have been doing the job 
                    # All previous days means a worker number should repeat in the list of workers who did that job day-1 times
                    g=[item for item, count in Counter(WhoAllPrev).items() if count == day-1]

                    # print("g",g)
                    for wp in g:
                        #if deltajw_yesterday == 1:
                        for i in range(len(Alljwdelta1)):
                            #find in which list this WONUM exists
                            if unfinWONUM[i] and wp in Alljwdelta1[i]:
                                #deltajw_yest = 1
                                #check proficiency level to be greater than 3
                                if int(workerskill(wp,str(q[j]))[1]) >= 3:
                                     thesew.append(wp)
                    # print("thesew",thesew)
                    if len(thesew) > 0:
                        cono += 1
                        contind.append([])
                        leftcontind.append([])
                        for w in thesew:
                            contind[cono].append(getxindex(j+1,w+1 ,1,numw,numt))
                            leftcontind[cono].append(1) 
                    # countit = 2
            
        ################### Constraint 16 ######################################################
        #Constraint 16 does not allow worker w to be assigned to job j if he is not continuously available for the hours needed for this job.
        consecW = []
        leftconsecW= []
        consecWRHS = []
        cej = -1   
        for j in lowerj:                   
            #Find w's in Cws>= 3
            theproficient = []
            for i in range(3,6):
                for k in qualifiedw(str(q[j]), i):
                    theproficient.append(k)
            #only unique values
            theproficient = np.unique(theproficient)
            # indexJ = dfJ["ORGjobno"].tolist().index(dfall["ORGjobno"].tolist()[j])
            indexJ = dfJ["WONUM"].tolist().index(dfall["WONUM"].tolist()[j])
            # indexJ = dfJ["HOURS"].tolist()[indexJ]
            for w in theproficient:
                consecW.append([])
                leftconsecW.append([])
                cej += 1
                #Left hand sidefor w in qualifiedw(str(q[j]), 1):
                consecW[cej].append(getxindex(j+1,w+1,8,numw,numt))
                leftconsecW[cej].append(HJ[indexJ])
                consecW[cej].append(getdeltajwindex(j+1,w+1,numw,numt))
                leftconsecW[cej].append(HJ[indexJ])
                consecWRHS.append(HJ[indexJ]+Ew[w])
        
        #################### Constraint 17 ####################################################
        #Constraint 16 does not allow worker w to be assigned to job j if he is not continuously available for the hours needed for this job.
        deltaj = []
        leftdeltaj= []
        dej = -1   
        for j in lowerj:                   
            deltaj.append([])
            leftdeltaj.append([])
            dej += 1
            #Find w's in Cws>= 3
            theproficient = []
            for i in range(3,6):
                for k in qualifiedw(str(q[j]), i):
                    theproficient.append(k)
            #only unique values
            theproficient = np.unique(theproficient)
            deltaj[dej].append(getaindex(j+1,len(lowerj),numw,numt))
            leftdeltaj[dej].append(-1)
            for w in theproficient:
    
                #Left hand sidefor w in qualifiedw(str(q[j]), 1):
                deltaj[dej].append(getdeltajwindex(j+1,w+1,numw,numt))
                leftdeltaj[dej].append(1)
                            
        #################### Constraint 15 ####################################################   
        # Workers are assigned based on their schedule (availability)
        indices15 = []
        fifteenleft= []
        fifRHS = []
        fp = -1   
        for w  in range(numw):
            for t  in range(0+ (day - 1)*8,8+ (day - 1)*8):
                fp += 1
                indices15.append([])
                fifteenleft.append([])
                fifRHS.append([])
                #does w exist in wlabel? - if not b = 0
                if w not in newdfcalw_bss['windex'].tolist(): #Mason for instance
                    #unavailable = 0
                    fifRHS[fp].append(0)
                    for j in lowerj:                                  
                        indices15[fp].append(getxindex(j+1,w+1 ,t - (day - 1)*8 +1,numw,numt))
                        fifteenleft[fp].append(1) 
                else:
                    #A list of 
                    ##### find e_wt 
                    filter_df_byw = newdfcalw_bss.loc[newdfcalw_bss['windex'] == w]  #windex
                    #save tindex column as a list
                    Wfiltered = filter_df_byw['tindex'].tolist()       #tindex  
                    #Ensure the person is doing a day shift (night shift workers and holiday rows are removed from the dataframe)
                    if t+1 in Wfiltered:
                        ix = Wfiltered.index(t+1)
        
                        #save tindex column as a list
                        isavailable = filter_df_byw['AVAILABILITY_TYPE'].tolist()
                        if isavailable[ix] == "Standard":
                            #1 means available
                              fifRHS[fp].append(1)
                        else:
                            #unavailable = 0
                            fifRHS[fp].append(0)
                    else:
                        fifRHS[fp].append(0)
                    for j in lowerj:                                  
                        indices15[fp].append(getxindex(j+1,w+1 ,t - (day - 1)*8 +1,numw,numt))
                        fifteenleft[fp].append(1) 
                    
        #################### Constraint 12 #####################################################
        # Sigma(Xjwt<w in Cws = 1>) = 0
        indskill = []
        leftskill= []
        sp = -1      
        for j in lowerj:                       
            if len(qualifiedw(str(q[j]), 1)) > 0:
                for t in range(numt):
                
                    sp += 1
                    indskill.append([])
                    leftskill.append([])
                    for w in qualifiedw(str(q[j]), 1):
    
                            #Left hand sidefor w in qualifiedw(str(q[j]), 1):
                            indskill[sp].append(getxindex(j+1,w+1 ,t+1,numw,numt))
                            leftskill[sp].append(1) 
               
        #################### Constraint 13 ###################################
        # Sigma(Xjwt<w in Cws = 5>)  - Sigma(Xjwt<w in Cws = 2>)>=  0 
        secindskill = []
        secleftskill= []
        sep = -1   
        for j in lowerj: 
              if len(qualifiedw(str(q[j]), 2)) > 0:
                    for t in range(numt):
                            sep += 1
                            secindskill.append([])
                            secleftskill.append([])
                            for w in qualifiedw(str(q[j]), 5):
            
                                #Left hand sidefor w in qualifiedw(str(q[j]), 1):
                                secindskill[sep].append(getxindex(j+1,w+1 ,t+1,numw,numt))
                                secleftskill[sep].append(1)
                                
                        # level 2   
                            for w in qualifiedw(str(q[j]), 2):
            
                                #Left hand sidefor w in qualifiedw(str(q[j]), 1):
                                secindskill[sep].append(getxindex(j+1,w+1 ,t+1,numw,numt))
                                secleftskill[sep].append(-1) 
    
        #******************************Constraint 2 *************************************
        # Each job should meet its duration requirenment. Sum over w and t = nj * hj  for all j
        indices12 = []
        twelveleft= []
        cp = -1    
        for j in lowerj:                       
            cp += 1
            indices12.append([])
            twelveleft.append([])
            indices12[cp].append(getaindex(j+1,len(lowerj),numw,numt))
            twelveleft[cp].append(-(ccrewz[j]*hhours[j]))
            for w  in range(numw):
                for t  in range(numt):
                    indices12[cp].append(getxindex(j+1,w+1 ,t+1,numw,numt))
                    twelveleft[cp].append(1)    
    
      #******************************Constraint 1  *************************************
        # Each worker can only be assigned to a maximum of one job at each time t. Sum across all jobs  Xjwt <= 1 For all w, all t
        indices13 = []
        thirteenleft= []
        cp = -1   
        for w  in range(numw):
            for t  in range(numt):
                cp += 1
                indices13.append([])
                thirteenleft.append([])
                for j in lowerj:                                  
                    indices13[cp].append(getxindex(j+1,w+1 ,t+1,numw,numt))
                    thirteenleft[cp].append(-1)    
      #******************************Constraint 3 *****************
        chap11= []
        ind11 = []
        cloop = -1 
        for j in lowerj:    
            if hhours[j] > 1:
                for w  in range(numw):
                    for t  in range(-1,numt):
                        if t + 1 < numt :
                            cloop += 1
                            ind11.append([])
                            chap11.append([])
                            for tau in range (1, hhours[j] + 1):       
                                if t + tau < (numt) :
                                    ind11[cloop].append(getxindex(j+1,w+1,tau + t+1,numw,numt))    
                                    chap11[cloop].append(1)
                            if t == -1:
                                for el in range(1):  
                                    ind11[cloop].append(getxindex(j+1,w+1,t+1+1,numw,numt))
                                    chap11[cloop].append(-1 * (hhours[j]))
                            else:
                                for el in range(1):   # Xjwt+1 + Xjwt
                                    ind11[cloop].append(getxindex(j+1,w+1,t+1+1,numw,numt))
                                    chap11[cloop].append(-1 * (hhours[j]))
                                    ind11[cloop].append(getxindex(j+1,w+1,t+1,numw,numt))
                                    chap11[cloop].append(+1 * (hhours[j]))
    
    ################################################# * constraint 5
        qpartcoeffb11 = []
        qleftb11= []
        qcounterloop = -1
        for t in range(numt):         
            for j in range(numJ):
                qcounterloop += 1   
                qpartcoeffb11.append([]) 
                qleftb11.append([])  
                for ij in jinJ[j]:
                    qpartcoeffb11[qcounterloop].append(getIjtindex(ij+1,t+1,numw,numt))    
                    qleftb11[qcounterloop].append(1)      
                        
    ######################################### *constraint 4
        partcoeffb11 = []
        leftb11= []
        counterloop = -1
        njfinder = []  
        
        for t in range(numt):         
            for j in lowerj:
                counterloop += 1
                partcoeffb11.append([])
                leftb11.append([])
                
                partcoeffb11[counterloop].append(getIjtindex(j+1,t+1,numw,numt))    
                leftb11[counterloop].append(-ccrewz[j])
                for w in range(numw):
                    partcoeffb11[counterloop].append(getxindex(j+1,w+1,t+1,numw,numt))    
                    leftb11[counterloop].append(1)               
                                                                    
        #******************************constrait zjt (constraint number 6 in the word doc "IP formulation")*************************************
        zjt = []
        zjtLHS= []
        kop = -1
        for j in lowerj:                   
            for t  in range(-1,numt):
    
                for w  in range(numw):
                    if (t+1 < numt):
                        if t == -1:
                            kop += 1
                            zjt.append([])
                            zjtLHS.append([])
                            zjt[kop].append(getzindex(j+1,t+1+1,numt))
                            zjtLHS[kop].append(1)
                            zjt[kop].append(getxindex(j+1,w+1 ,t + 1+1,numw,numt))
                            zjtLHS[kop].append(-1)
                        else:
                            kop += 1
                            zjt.append([])
                            zjtLHS.append([])
                            zjt[kop].append(getzindex(j+1,t+1+1,numt))
                            zjtLHS[kop].append(1)
                            zjt[kop].append(getxindex(j+1,w+1 ,t + 1+1,numw,numt))
                            zjtLHS[kop].append(-1)
                            zjt[kop].append(getxindex(j+1,w+1 ,t+1,numw,numt))
                            zjtLHS[kop].append(+1)
        
    #******************************constrait zz (constraint number 7 in the word doc "IP formulation")*************************************
        zz = []
        zzLHS= []
        zop = -1
        for j in lowerj:                   
            zop += 1
            zz.append([])
            zzLHS.append([])
            zz[zop].append(getaindex(j+1,len(lowerj),numw,numt))
            zzLHS[zop].append(-1)
            for t  in range(numt):
                zz[zop].append(getzindex(j+1,t+1,numt))
                zzLHS[zop].append(1)
            
        #******************************Constraint tj = sigma Zjwt * t + (nj * hj) (constraint number 8 in the word doc "IP formulation") *************************************
        #tj^c = summation Yjt * t + (nj * hj)
        # Create  tj^c - summation Yjt   as the right hand size    
        tJc = []
        tJLHS= []
        lop = -1  
        #hhours = updated hours in the post split list of jobs
        hz = []
        for j in range(len(jinJ)): # for each member of J we need the number of its parts = len(samegam[jj])     
            if HJ[j] > 0:
                # the number of tJ equations for job J equals the number of its parts with the same gamma
                for jj in jinJ[j]: 
                    # hjiiz = 0
                    tJc.append([])
                    tJLHS.append([])
                    lop += 1
                    tJc[lop].append(gettindex(j+1,numJ,numw,numt))  
                    tJLHS[lop].append(1)
                    tJc[lop].append(getaindex(jj+1,len(lowerj),numw,numt)) #ajj
                    tJLHS[lop].append(-hhours[jj] + 1)
                    for t  in range(numt):
                        tJc[lop].append(getzindex(jj+1,t+1,numt))
                        tJLHS[lop].append(-(t+1))  
                    
        #**** The additional tJc constraint  (9)
        additJc = []  #additional tJ constraint
        additJLHS= [] 
        alop = -1
        sumhj = 0
        #hhours = updated hours in the post split list of jobs
        addiRhz = []
        for j in range(numJ): # for each member of J we need the number of its parts = len(samegam[jj])
            if HJ[j] > 0:
                sumhj = 0
                additJc.append([])
                additJLHS.append([])
                alop += 1
                additJc[alop].append(gettindex(j+1,numJ,numw,numt))  
                additJLHS[alop].append(1)
                additJc[alop].append(getyindex(j+1,numJ,numw,numt))  
                additJLHS[alop].append(numt)
                for jjj in jinJ[j]: #for all the other aj's
                    additJc[alop].append(getaindex(jjj+1,len(lowerj),numw,numt))
                    additJLHS[alop].append(hhours[jjj])
                    sumhj += hhours[jjj]
                addiRhz.append(sumhj + numt)
            
    #**** The last tJc constraint  (10)
        aJcon = []  #additional tJ constraint
        leftaJcon= [] 
        ap = -1
    
        for j in range(numJ): # for each member of J we need the number of its parts = len(samegam[jj])
    
            if HJ[j] > 0:
                for jjj in jinJ[j]: #for all the other aj's
                    aJcon.append([])
                    leftaJcon.append([])
                    ap += 1
                        #y_J
                    aJcon[ap].append(getyindex(j+1,numJ,numw,numt))  #we want tJ, so we need index j not jj
                    leftaJcon[ap].append(1)
                    aJcon[ap].append(getaindex(jjj+1,len(lowerj),numw,numt))
                    leftaJcon[ap].append(-1)
    
        #******************************Constraint tj-dd<= 0 (constraint number 11 in the word doc "IP formulation")  *************************************
        td = []
        fourteenleft= []
        lloopp = -1
        tiiz=[]
        for j in range(len(jinJ)):
            if Ypm[j] == 1 and due[j]!= 0 :
                td.append([])
                fourteenleft.append([])
                lloopp += 1
                td[lloopp].append(gettindex(j+1,numJ,numw,numt))
                tiiz.append(j)
                fourteenleft[lloopp].append(1)
    
        ####################################### Constraint 14 ######################################################    
        #the new constraint to ensure jobs with duration less than hours finish within a day
        dayshift = []
        leftdayshift= []
        shp = -1
        for j in lowerj:                  
            if 0 < hhours[j] <= 8:
                shp += 1
                dayshift.append([])
                leftdayshift.append([])
        
                dayshift[shp].append(getaindex(j+1,len(lowerj),numw,numt))
                leftdayshift[shp].append(-1)
                #for every number of shifts (numb) (8-hour blocks)
                if numt > 8:
                    ck = 0
                    while ck <= numb - 1:
                        for t  in range(ck * 8 , ck * 8 + 8 - hhours[j] + 1):
                            dayshift[shp].append(getzindex(j+1,t+1,numt))
                            leftdayshift[shp].append(1)
                        ck += 1
                else:
                    for t  in range(0, 8 - hhours[j] + 1):
                        if t < numt:
                            dayshift[shp].append(getzindex(j+1,t+1,numt))
                            leftdayshift[shp].append(1)
    
#%% ######## CPLEX requires the rows to have unique indices for which the following actions are done ##################################################
        hindices13 = indices13
        hthirteenleft = thirteenleft
        for i in range(len(indices13)):      
            indices13[i], thirteenleft[i] = removedupl(hindices13[i],hthirteenleft[i])
    
        hindices12 = indices12
        htwelveleft = twelveleft
        for i in range(len(indices12)):
            indices12[i], twelveleft[i] = removedupl(hindices12[i],htwelveleft[i])  
           
        hind11 = ind11
        hchap11 = chap11
        for i in range(len(ind11)):
            ind11[i], chap11[i] = removedupl(hind11[i],hchap11[i])
        
        hpartcoeffb11 = partcoeffb11
        hleftb11 = leftb11
        for i in range(len(partcoeffb11)):
            partcoeffb11[i], leftb11[i] = removedupl(hpartcoeffb11[i],hleftb11[i])
          
        hzjt = zjt
        hzjtLHS = zjtLHS
        for i in range(len(zjt)):
            zjt[i], zjtLHS[i] = removedupl(hzjt[i],hzjtLHS[i])  
            
        hzz = zz
        hzzLHS = zzLHS
        for i in range(len(zz)):
            zz[i], zzLHS[i] = removedupl(hzz[i],hzzLHS[i])  
            
        htJc = tJc
        htJLHS = tJLHS
        for i in range(len(tJc)):
            tJc[i], tJLHS[i] = removedupl(htJc[i],htJLHS[i])  
    
        htd = td
        hfourteenleft = fourteenleft
        for i in range(len(td)):
            td[i], fourteenleft[i] = removedupl(htd[i],hfourteenleft[i])   
         
        hskl = indskill
        hskillleft = leftskill
        for i in range(len(indskill)):
            indskill[i], leftskill[i] = removedupl(hskl[i],hskillleft[i])   
            
        hsecskl = secindskill
        hsecskillleft = secleftskill
        for i in range(len(secindskill)):
            secindskill[i], secleftskill[i] = removedupl(hsecskl[i],hsecskillleft[i])
            
        hdayshift = dayshift
        hleftdayshift = leftdayshift
        for i in range(len(dayshift)):
            dayshift[i], leftdayshift[i] = removedupl(hdayshift[i],hleftdayshift[i])   
    
        hadditJc = additJc
        hadditJLHS = additJLHS
        for i in range(len(additJc)):
            additJc[i], additJLHS[i] = removedupl(hadditJc[i],hadditJLHS[i])  
               
        haJcon = aJcon
        hleftaJcon = leftaJcon
        for i in range(len(aJcon)):
            aJcon[i], leftaJcon[i] = removedupl(haJcon[i],hleftaJcon[i])  
            
        hqpartcoeffb11 = qpartcoeffb11
        hqleftb11 = qleftb11
        for i in range(len(qpartcoeffb11)):
            qpartcoeffb11[i], qleftb11[i] = removedupl(hqpartcoeffb11[i],hqleftb11[i])   
    
        hindices15 = indices15
        hfifteenleft = fifteenleft
        for i in range(len(indices15)):
            indices15[i], fifteenleft[i] = removedupl(hindices15[i],hfifteenleft[i])  
         
        hdeltaj = deltaj
        hleftdeltaj = leftdeltaj
        for i in range(len(deltaj)):
            deltaj[i], leftdeltaj[i] = removedupl(hdeltaj[i],hleftdeltaj[i])  
        
        hconsecW = consecW
        hleftconsecW = leftconsecW
        for i in range(len(consecW)):
            consecW[i], leftconsecW[i] = removedupl(hconsecW[i],hleftconsecW[i]) 
        
        hcontind = contind
        hleftcontind = leftcontind
        for i in range(len(contind)):
            contind[i], leftcontind[i] = removedupl(hcontind[i],hleftcontind[i])  
    
        houtj = outj
        hleftoutj = leftoutj
        for i in range(len(outj)):
            outj[i], leftoutj[i] = removedupl(houtj[i],hleftoutj[i])    
            
        hdelx = delx
        hleftdelx = leftdelx
        for i in range(len(delx)):
            delx[i], leftdelx[i] = removedupl(hdelx[i],hleftdelx[i])
#%%  # Create the left hand side
        myLHS = []
        # Create the right hand side
        my_RHS = [] 
        for i in range(numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11)+ len(zjt) + len (zz) + len(tJc)+ len(td)+len(indskill)+ len(secindskill)+len(dayshift)+ len(additJc)+len(aJcon) + len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)+len(contind)+len(outj)+len(delx)):
            myLHS.append([])
            my_RHS.append([])
        #constraint 1  
        for i in range(numw * numt):
            myLHS[i].append(indices13[i]) 
            myLHS[i].append(thirteenleft[i])
            my_RHS[i].append(-1)
        #constraint 2  
        for i in range(len(lowerj)):
            myLHS[i+ numw * numt].append(indices12[i])
            myLHS[i+ numw * numt].append(twelveleft[i])  
            my_RHS[i+ numw * numt].append(0)
    
        #constraint 3
        for i in range(len(ind11)):     
            myLHS[i+ numw * numt + len(lowerj)].append(ind11[i])
            myLHS[i+ numw * numt + len(lowerj)].append(chap11[i]) 
            my_RHS[i+ numw * numt + len(lowerj)].append(0)
                     
        #constraint 4.a
        for i in range(len(partcoeffb11)):       
            myLHS[i+ numw * numt + len(lowerj) + len(ind11)].append(partcoeffb11[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11)].append(leftb11[i])
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11)].append(0) 
    
        #constraint 5      
        for i in range(len(zjt)):
            if len(zjt[i]) > 0:
                myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11)].append(zjt[i])
                myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11)].append(zjtLHS[i])
                my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11)].append(0)
    
        #constraint 6       
        for i in range(len(zz)):
            if len(zz[i]) > 0:
                myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)].append(zz[i])
                myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)].append(zzLHS[i])
                my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)].append(0)          
    
        # constraint 7       
        for i in range(len(tJc)):
            # repeats 12 times print(i+ numw * numt + len(lowerj) + len(ind11) + len(bigsumtau) + len(zxx))
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+len(zz)].append(tJc[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+len(zz) ].append(tJLHS[i]) 
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz)].append(0)
    
        #constraint 8
        for i in range(len(td)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc)].append(td[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc)].append(fourteenleft[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc)].append(due[tiiz[i]])  #due for capital j      
    
        #costraint 9
        for i in range(len(indskill)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)].append(indskill[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)].append(leftskill[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)].append(0)        
    
        #constraint 10
        for i in range(len(secindskill)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)].append(secindskill[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)].append(secleftskill[i])      
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill)].append(0)        
    
        #constraint 11   
        for i in range(len(dayshift)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)].append(dayshift[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)].append(leftdayshift[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)].append(0)        
    
        #constraint 7.b
        for i in range(len(additJc)):
            # repeats 12 times print(i+ numw * numt + len(lowerj) + len(ind11) + len(bigsumtau) + len(zxx))
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt) + len(zz) + len(tJc)+ len(td)+ len(indskill)+len(secindskill)+len(dayshift)].append(additJc[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt) + len(zz) + len(tJc)+ len(td)+ len(indskill)+len(secleftskill)+len(leftdayshift)].append(additJLHS[i]) 
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)].append(addiRhz[i])        
    
        #constraint 7-3
        for i in range(len(aJcon)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)].append(aJcon[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(leftdayshift)+len(additJc)].append(leftaJcon[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)].append(0)        
    
        for i in range(len(qpartcoeffb11)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)].append(qpartcoeffb11[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(leftdayshift)+len(additJc)+len(leftaJcon)].append(qleftb11[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)].append(1)        
    
        for i in range(len(indices15)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)].append(indices15[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(leftdayshift)+len(additJc)+len(leftaJcon)+len(qleftb11)].append(fifteenleft[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)].append(fifRHS[i][0])        
    
        for i in range(len(deltaj)):
    #        if len(deltaj[i]) > 0:
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)].append(deltaj[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(leftdayshift)+len(additJc)+len(leftaJcon)+len(qleftb11)+len(fifteenleft)].append(leftdeltaj[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)].append(0)        
    
        for i in range(len(consecW)):
    #        if len(consecW[i]) > 0:
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)].append(consecW[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(leftdayshift)+len(additJc)+len(leftaJcon)+len(qleftb11)+len(fifteenleft)+len(leftdeltaj)].append(leftconsecW[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)].append(consecWRHS[i])    #consecWRHS[i][0]    
    
        for i in range(len(contind)):
    #        if len(consecW[i]) > 0:
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)].append(contind[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td)+ len(indskill)+len(secindskill)+len(leftdayshift)+len(additJc)+len(leftaJcon)+len(qleftb11)+len(fifteenleft)+len(leftdeltaj)+len(leftconsecW)].append(leftcontind[i])  
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)].append(1)    #consecWRHS[i][0]    
    
        for i in range(len(outj)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt) + len(zz) + len(tJc)+ len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)+len(contind)].append(outj[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt) + len(zz) + len(tJc)+ len(td)+ len(indskill)+len(secleftskill)+len(leftdayshift)+len(additJLHS)+len(leftaJcon)+len(qleftb11)+len(fifteenleft)+len(leftdeltaj)+len(leftconsecW)+len(leftcontind)].append(leftoutj[i]) 
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)+len(contind)].append(rightoutj[i])    #0.75*hj  
    
        for i in range(len(delx)):
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt) + len(zz) + len(tJc)+ len(td)+ len(indskill)+len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)+len(contind)+len(outj)].append(delx[i])
            myLHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt) + len(zz) + len(tJc)+ len(td)+ len(indskill)+len(secleftskill)+len(leftdayshift)+len(additJLHS)+len(leftaJcon)+len(qleftb11)+len(fifteenleft)+len(leftdeltaj)+len(leftconsecW)+len(leftcontind)+len(leftoutj)].append(leftdelx[i]) 
            my_RHS[i+ numw * numt + len(lowerj) + len(ind11) + len(partcoeffb11) + len(zjt)+ len(zz) + len(tJc) + len(td) + len(indskill) + len(secindskill)+len(dayshift)+len(additJc)+len(aJcon)+len(qpartcoeffb11)+len(indices15)+len(deltaj)+len(consecW)+len(contind)+len(outj)].append(0)    #0.75*hj  
    
        b=[]
        for i in range(len(my_RHS)): 
            b.append(my_RHS[i][0])    
        
        return  indices13,indices12,ind11,partcoeffb11,zjt,zz, tJc,td,indskill,secindskill,dayshift,njfinder,tiiz,hz,additJc,addiRhz,aJcon,qpartcoeffb11,indices15,fifRHS,deltaj,consecW,consecWRHS,contind,outj,rightoutj,delx, myLHS, b
    
#%% Create objective function
    def Objcoeff():   
        #Find the objective function
        my_obj = []
    
        # C_obj for X and Z iz target_week
        for i in range(numw * numt * len(lowerj) + numt * len(lowerj)):
            my_obj.append(0)
        # C_obj for tc iz found at tcj_obj
    
    #Reverse J
        tempnumJ = list(range(numJ))
        tempnumJ.sort(reverse = True)
        
        for j in range(numJ):  
            #Make the coefficient of t variables by adding 1000 to the job number (first job = 0) plus one : 0.000j++
            decim = 0.0001 * ( tempnumJ[j] + 1)
            #Add a coefficient in front of t that is 1.index (e.g., 1.0001 - 1.0061)
            tcof = 1 + decim
            my_obj.append((1 - Ypm[j]) * tenpower(j) * tcof - Ypm[j] * tenpower(j) * tcof)
      
        #aj
    #    for i in range(numw * numt * numJ + numt * numJ):
        for i in range(len(lowerj)):
            my_obj.append(0)
    
        #yJ
        for i in range(numJ):
            my_obj.append(0)
            
        #Ijt
        for i in range(len(lowerj) * numt):
            my_obj.append(0)
                    #deltajw
        for i in range(len(lowerj)* numw):
            my_obj.append(0)
            
        return my_obj        
  
#%% Define constraint types
    def constype(indices13,indices12,ind11,partcoeffb11,zjt,zz,tJc,td,indskill,secindskill,dayshift,additJc,aJcon,qpartcoeffb11,indices15,deltaj,consecW,contind,outj,delx):
        # Define the constraints' type
        my_constraint=""
    
        for i in range(numw * numt):
            my_constraint = my_constraint+"G"
    
        for i in range(len(lowerj)):
            my_constraint = my_constraint+"E"
    
        for i in range(len(ind11)):
            my_constraint =my_constraint+"G"
        
        for i in range(len(partcoeffb11)):
            my_constraint =my_constraint+"E"
        
        for i in range(len(zjt)):
            my_constraint =my_constraint+"G"
        
        for i in range(len(zz)):
            my_constraint =my_constraint+"E"
    
        for i in range(len(tJc)):
            my_constraint = my_constraint+"G"
          
        for i in range(len(td)):
            my_constraint = my_constraint+"L"
        
        for i in range(len(indskill)):
            my_constraint = my_constraint+"E"
            
        for i in range(len(secindskill)):
            my_constraint = my_constraint+"G"
                
        for i in range(len(dayshift)):
            my_constraint = my_constraint+"E"
                        
        for i in range(len(additJc)):
            my_constraint = my_constraint+"G"
            
        for i in range(len(aJcon)):
            my_constraint = my_constraint+"L"
            
        for i in range(len(qpartcoeffb11)):
            my_constraint =my_constraint+"L"
    
        for i in range(len(indices15)):
            my_constraint = my_constraint+"L"
        
        for i in range(len(deltaj)):
            my_constraint = my_constraint+"G"
            
        for i in range(len(consecW)):
            my_constraint = my_constraint+"L"
        
        for i in range(len(contind)):
            my_constraint = my_constraint+"G"
                
        for i in range(len(outj)):
            my_constraint = my_constraint+"G"
            
        for i in range(len(delx)):
            my_constraint = my_constraint+"G"
        return my_constraint
    #*****************************************************************
    def workdays(d, end, excluded=(6, 7)):
        days = []
        while d.date() <= end.date():
            if d.isoweekday() not in excluded:
                days.append(d)
            d += datetime.timedelta(days=1)
        return days

#%%*********************** Main Program ****************************
    # if __name__ == "__main__":
        
    #_______________ Calculate yj ________________
    Ypm = [] 
    
    for i in range(len(pJ)):
        # There are some CM jobs with priority[i] = 4
        if pJ[i] == 4 and due[i] != 0:
              Ypm.append(1)
        else:
              Ypm.append(0)  
    #_______________ End of Calculating yj ________________
    indices13,indices12,ind11,partcoeffb11,zjt,zz,tJc,td,indskill,secindskill,dayshift,njfinder,tiiz,hz,additJc,addiRhz,aJcon,qpartcoeffb11,indices15,fifRHS,deltaj,consecW,consecWRHS,contind,outj, rightoutj,delx, myLHS,b = createLRHS()
    my_obj  = Objcoeff()
    my_constraint = constype(indices13,indices12,ind11,partcoeffb11,zjt,zz,tJc,td,indskill,secindskill,dayshift,additJc,aJcon,qpartcoeffb11,indices15, deltaj,consecW,contind,outj,delx)
    myProblem = cplex.Cplex()
    myProblem.objective.set_sense(myProblem.objective.sense.minimize)
    my_var_type = ""  
    
    for i in range(numw * numt * len(lowerj)):
        my_var_type = my_var_type+"B"
        
    for i in range(numt * len(lowerj)):
        my_var_type = my_var_type+"B"
        
    for i in range(numJ):  #tJ
        my_var_type = my_var_type+"I"  #Integer
        
    #aj
    for i in range(len(lowerj)):
        my_var_type = my_var_type+"B"
        
    # yJ
    for i in range(numJ):  
        my_var_type = my_var_type+"B"  #Binary
        
      # Ijt
    for i in range(len(lowerj) * numt):  
        my_var_type = my_var_type+"B"  #Binary
    
                # deltajw
    for i in range(len(lowerj)* numw):  
        my_var_type = my_var_type+"B"  #Binary 
    
    my_lb = []
    for i in range(num_decision_var):
        my_lb.append(0)
    #        
    my_ub = []
    for i in range(num_decision_var):
        my_ub.append(1000)
      
    # Add constraints
    myProblem.variables.add(obj=my_obj, lb=my_lb, ub=my_ub, types=my_var_type)
    myProblem.linear_constraints.add(lin_expr=convert_to_int(myLHS), senses=my_constraint, rhs=b)
    
    ## Add objective function and set its sense
    for i in range(num_decision_var):
        myProblem.objective.set_linear([(i, my_obj[i])])       
        
    ##################################### GAP ######################################################
    myProblem.parameters.mip.tolerances.mipgap = 0 #0.005
    
    # Write the LP file   
    myProblem.write("lp_file_.lp")
    
    myProblem.parameters.timelimit.set(runtime) 
    ## Solve the model and print the answer  
    myProblem.solve()  
    
    # Obj function val
    obj_val = myProblem.solution.get_objective_value()
    print("obj_val",obj_val)
    # get variable value
    var_vals = myProblem.solution.get_values()
    #Round the solution to avoid having 0.99999 instead of 1 - round to three decimal points
    var_vals = [ round(x,3) for x in var_vals]
    
    ########################################## Solution ##############################################
    
    solo = findjwt(var_vals[0:len(lowerj)*numw*numt])
    # Show the solution in the form of a table
    Mx, pt = matrix2table(numt,numw,var_vals[0:len(lowerj)*numw*numt],solo)
    #%% ############ Print table and legends###################################
    fig, ax = pl.subplots()
    ax.axis('tight')
    ax.axis('off')
    
    cellaviz = pt
    norm = pl.Normalize(1,7)
    colours = pl.cm.terrain(norm(cellaviz))
    the_table = ax.table(cellText=Mx,cellLoc='center',fontsize=26,cellColours=colours)
    
    scheduledJ = []
    scheduledj = []
    for i in range(len(var_vals[0:len(lowerj)*numw*numt])):   #solo[i][0] = j* (starting from 1) #solo[i][0]-1 = job number starting from 0
        if var_vals[i] == 1.0:
            #j = solo[i][0] - 1 ,#w = solo[i][1] - 1, starting from 0 , 
            workercolor(solo[i][0] - 1,solo[i][1] ,solo[i][2] )
            scheduledj.append(solo[i][0]-1) 
            scheduledJ.append(dfall.iloc[solo[i][0]-1]["ORGjobno"])
    #job scheduledj's that were scheduled this day
    scheduledj = list(dict.fromkeys(scheduledj))
    scheduledJ = list(dict.fromkeys(scheduledJ))
    ##make the header and the first ccolumn WHITE:   
    for i in range(len(Mx[0])):
        the_table._cells[(0, i)].set_facecolor("white") 
    for i in range(len(Mx)):
        the_table._cells[(i, 0)].set_facecolor("white")
    
    #The background table is all black (empty calls should be noticeable)
    for w in range(1,numw+1):
        for t in range(1,numt+1):
            if Mx[w][t] == 0:
                  the_table._cells[(w, t)].set_facecolor("black")
    
    #%% worker legend on day 1 only 
    if day == 1:
        the_table.auto_set_font_size(False)
        the_table.set_fontsize(22)
        the_table.scale(4, 4)
        pl.show()
        
        #legend
        text=[["1","" ],["2",""],["3", ""],["4", ""],["5", ""]]
        colLabels = ["Proficiency level", "Number color"]
        
        legi=pl.table(cellText=text, colLabels=colLabels, 
                            colWidths = [0.2,0.2], loc='lower right')
        
        legi._cells[(1, 1)].set_facecolor("darkorchid")
        legi._cells[(2, 1)].set_facecolor("deeppink")
        legi._cells[(3, 1)].set_facecolor("red")
        legi._cells[(4, 1)].set_facecolor("darkorange")
        legi._cells[(5, 1)].set_facecolor("seagreen")
        
        ax = fig.add_subplot()
        legi.auto_set_font_size(False)
        pl.axis('off')
        legi.set_fontsize(14)
        legi.scale(2,2)
        
        pl.show()
        
        # job legend
        textjob=[["1","" ],["2",""],["3", ""],["4", ""],["5", ""]]
        coljobLabels = ["Job priority level", "Cell color"]
        
        legijob=pl.table(cellText=textjob, colLabels=coljobLabels, 
                            colWidths = [0.2,0.2], loc='center right')
        
        legijob._cells[(1, 1)].set_facecolor("darkblue")
        legijob._cells[(2, 1)].set_facecolor("deepskyblue")
        legijob._cells[(3, 1)].set_facecolor("springgreen")
        legijob._cells[(4, 1)].set_facecolor("yellow")
        legijob._cells[(5, 1)].set_facecolor("tan")
        
        #ax = fig.add_subplot()
        legijob.auto_set_font_size(False)
        pl.axis('off')
        legijob.set_fontsize(14)
        legijob.scale(2,2)
                   
        pl.show() 
        
    #%% Save optimal variable values:
    optaj = var_vals[len(lowerj) * numw * numt + len(lowerj) * numt + numJ:len(lowerj) * numw * numt + len(lowerj) * numt + numJ+ len(lowerj)]
    opty =  var_vals[len(lowerj) * numw * numt + len(lowerj) * numt + numJ+ len(lowerj) :len(lowerj) * numw * numt + len(lowerj) * numt + numJ+ len(lowerj) + numJ]
    optx = var_vals[0:len(lowerj) * numw * numt]
    optdelta = var_vals[len(lowerj) * numw * numt + len(lowerj) * numt + numJ+ len(lowerj) + numJ + len(lowerj) * numt:len(lowerj) * numw * numt + len(lowerj) * numt + numJ+ len(lowerj) + numJ + len(lowerj) * numt + len(lowerj)* numw]

    #%% Write the output to a csv file
    wonumtocsv = []
    workertocsv = [] 
    startdh = []
    plandaytocsv = []
    finire = []
    #Optimal Xjwt
    # Xs = var_vals[0:len(lowerj)*numw*numt]
    for w in range(1,numw+1):
        for t in range(1,numt+1):
            if Mx[w][t] != 0:    
                ###################### WONMU #######################################
                #Mx[w][t]!= 0 is the work order number
                wonumtocsv.append(Mx[w][t])
                #################### WORKER ID ####################################
                #Which worker did it? On newdfcalw_bss worker number starts from 0
                w_indx = newdfcalw_bss["windex"].tolist().index(w-1)
                workertocsv.append(newdfcalw_bss["EMPLOYEE_ID"].tolist()[w_indx])
                ###################### START DATE/HOUR/MIN########################
                #Which hour 
                #Filter to worker w
                filterw = newdfcalw_bss.loc[newdfcalw_bss['windex'] == w-1]  #Bronx
                filterw.reset_index(drop=True, inplace=True)
                td_indx = filterw["tindex"].tolist().index((day -1)* 8 +t )
                starthour = filterw["SHIFT_START"].tolist()[td_indx]
                #Delete the last 9 elements to only have the date in this format:2020-08-03
                starthour = starthour[:-9]
                #A dictionary to map hour from 1 to 8 to 8 am to 16 pm
                hourdic = {1:"08", 2:"09", 3:"10", 4:"11", 5:"13", 6:"14", 7:"15", 8:"16"}
                ############################################################################
                #start time 
                zjtsol = var_vals[len(lowerj) * numw * numt:len(lowerj) * numw * numt + len(lowerj) * numt ] 

                op = -1
                for jx in range(len(lowerj)):                
                    for tx in range(numt):
                        op += 1
                        if zjtsol[op] == 1:
                            if dfall["WONUM"].tolist()[jx] == Mx[w][t]:
                                #This t is the t that makes Zjt = 1
                                thishour = hourdic.get(tx+1)
                                #"datehourminute"
                                startdh.append(starthour+" "+thishour+":00:"+"00") 
                                #Zjt + hj -1 = completion time
                                fx = tx+1 + hhours[jx] - 1
                                finhour = hourdic.get(fx)
                                finire.append(starthour+" "+finhour+":00:"+"00")
                ######################### Finish Time ##############################
    
        # Use the list wonumtocsv to find the index of the duplicates of consecutive elements that must be deleted from each of the other lists ro be going to be added to the csv file 
        listix = list(range(len( wonumtocsv)))
        previous_value = None
        new_lst = []
        theunique = []
        indexsave = -1
        for elem in wonumtocsv:
            indexsave += 1
            if elem != previous_value:
                #save index of the unique elements
                theunique.append(indexsave)
                new_lst.append(elem)
                previous_value = elem    
    
        #for this wonum, fnd planday:
        for u in new_lst:
            specialix = dfall["WONUM"].tolist().index(u)
            plandaytocsv.append(dfall["DAY_NUMBER"].tolist()[specialix])
    
        #indexes to be deleted
        remove_indx = []
        for i in listix:
            if i not in theunique :
                remove_indx.append(i)
        #Delete the indexes represented in tobedeleted from the following lists
        wonumtocsv = [i for j, i in enumerate(wonumtocsv) if j not in remove_indx]
        workertocsv = [i for j, i in enumerate(workertocsv) if j not in remove_indx]
        startdh = [i for j, i in enumerate(startdh) if j not in remove_indx]
        finire  = [i for j, i in enumerate(finire) if j not in remove_indx]
    
        scheduled_list = pd.DataFrame(
        {'Plan Day':plandaytocsv, 'WONUM': wonumtocsv,
        'EmployeeID':workertocsv, 'Start Date/Time':startdh,'Finish Date/Time':finire, })
    
        with open('dailyoutputcsv.csv', 'a') as f:
            scheduled_list.to_csv(f, header=False, index=False, line_terminator='\n', quoting=csv.QUOTE_NONNUMERIC)
            
        wonumtocsv = []
        workertocsv = []
        startdh = []
        finire = []
        plandaytocsv = []
        
    return optaj, opty, optx, optdelta;

#%%************Sequential Optimization (Repeat optimization 5 times to get a weeklong schedule)**************
while day <=5:
    #Run the integer programming model to get a one day (8-hour) schedule
    optaj, opty, optx, optdelta = dailyoptimization()

    # Using the results, identify started, unfinished Jobs: sum(a_j) = 1 and y_J = 0
    dfg = dfall.copy()
    Hg = HJ
    dayg1 = 1
   
    #%% Identify Js which started but not yet finished, which should continue next day:
    startednotf = []
    for i in range(len(jinJ)):   #for J
        sumaj = 0
        for j in range(len(jinJ[i])):
            sumaj += optaj[jinJ[i][j]] 
        # if sum aj J = 0
        if sumaj == 1.0 and opty[i] == 0.0:
            startednotf.append(i)
    
    unfinWONUM = []
    assignedw= []
    # workingc = []
    counter1 = -1
    for i in startednotf:
        counter1 += 1
        workingc = []
        # Make a list of WONUMs of Jobs that must continue
        unfinWONUM.append(dfJ.iloc[i]["WONUM"])
        # Find the workers in the schedule matrix, Mx
        for u in range(len(Mx[1:])):
            for v in range(1,9):
                # if Mx[1:][u][v] != 0 :
                if Mx[1:][u][v] == dfJ.iloc[i]["WONUM"]: #v is the hour when that specific job finishes
                    workingc.append(u)
        workingc = list(dict.fromkeys(workingc))
        assignedw.append(workingc)
        # Add workers to the row with this wonum in dfJ
        # For which job you want to record the workers who were doing it?
        # if the workers doing the job the job before are not doing it today, remove them from the list
        # All the occurences of this WONUM in dfall
        indices = [l for l, x in enumerate(list(dfall.WONUM)) if x == dfJ.iloc[i]["WONUM"]]
        for f in indices:
            dfall.at[f, 'wtocont'].append(assignedw[counter1])

    #%% Identify deltajw(Jx,wp) == 1
    Alljwdelta1 = []
    ctr = -1
    for unfin in unfinWONUM:  #work order number of the unfinished jobs
        Alljwdelta1.append([])
        ctr+= 1
        for w in range(numw):
            #Find j of this job
            j = dfall["WONUM"].tolist().index(unfin)
            #if deltajw* == 1: add this pair of wonum and w to a dict
            if optdelta[w+(j)*numw ] == 1:
                #Add this WONUM to a list and then append all w's whose deltajw =1 to it E.g. ['16558158',1,2,3,4,5,6,7,8]
                Alljwdelta1[ctr].append(unfin)
                Alljwdelta1[ctr].append(w)

    #%% Update the hours of jobs that started on a day and its duration is less than or equal to 8
    for i in scheduledJ:
        if HJ[i] <= 8:
            HJ[i] = 0
        else:
            #Update the hour of a job thst should continue in the following days( will then remove it from scheduled1)   
            #find all occurrences of job J in the list of ORGjobno
            indices = [e for e, x in enumerate(list(dfall.ORGjobno)) if x == i]
            for k in indices:
                #find which shift of a multiple shoft job was scheduled
                if k in scheduledj:
                    HJ[i] = HJ[i] -  dfall.iloc[k]["HOURS"]
    #Update hours
    for i in scheduledj:
        hhours[i] = 0
        #The scheduledjobs ( hhours <= 8) will then have a zero hour and should be deleted
    dfall["HOURS"] = hhours    

    # Remove rows with HOURS = 0 in dfall
    #Remove completed jobs from the dataframe
    dfall = dfall.drop(scheduledj) 
    #Reset indices
    dfall.index = range(len(dfall.index))
    #%% Update the index of completed J's
    completedJ= list(set(startednotf).difference(scheduledJ))
    dfJ = dfJ.drop(completedJ) 
    dfJ.index = range(len(dfJ.index))

#%% Add the removed job back to be considered in the next day optimization
    for i in range(len(removedrow)):
    #       # We want the row could be added from dfJ not df
        dfall = dfall.append(removedrow[i], ignore_index=True)

    # print(dfall) 
    removedrow = [] 
#%% This updated dataframe (dfall) will be used in the next iteration
    dfcopy = dfall.copy()
    # Go to the next day    
    day += 1
    
#The rows of the last updated df are jobs that are not scheduled or not completed
#%%*********** Write output file *************************************   
# If it already exists, delete the old one first:
if os.path.isfile('output_weekly_schedule.csv'):
    os.remove('output_weekly_schedule.csv')
    
dof = pd.read_csv('dailyoutputcsv.csv', header=None)
dof.columns = ['Plan Day','WONUM','EmployeeID','Start Date/Time','Finish Date/Time']
dof.to_csv('output_weekly_schedule.csv',mode = 'w', index=False)

# Remove redundant dailyoutputcsv.csv file
if os.path.isfile('dailyoutputcsv.csv'):
    os.remove('dailyoutputcsv.csv')

print("Final %s seconds ---" % (time.time() - start_time))