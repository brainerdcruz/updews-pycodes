#Importing relevant functions
from datetime import datetime, date, time, timedelta
import pandas as pd
import numpy as np
import ConfigParser
from scipy import stats
import os
import sys
import platform
from sqlalchemy import create_engine
import matplotlib.pyplot as plt

#Include the path of "Data Analysis" folder for the python scripts searching
path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if not path in sys.path:
    sys.path.insert(1,path)
del path 
from querySenslopeDb import *

#Check the current OS of the machine
curOS = platform.system()

#import MySQLdb according to the OS
if curOS == "Windows":
    import MySQLdb
elif curOS == "Linux":
    import pymysql as MySQLdb

#####################Defining important local functions
def up_one(p):
    #INPUT: Path or directory
    #OUTPUT: Parent directory
    out = os.path.abspath(os.path.join(p, '..'))
    return out  

def get_rt_window(rt_window_length,roll_window_size,num_roll_window_ops):
    ##INPUT:
    ##rt_window_length; float; length of real-time monitoring window in days
    ##roll_window_size; integer; number of data points to cover in moving window operations
    
    ##OUTPUT: 
    ##end, start, offsetstart; datetimes; dates for the end, start and offset-start of the real-time monitoring window 

    ##set current time as endpoint of the interval
    end=datetime.now()

    ##round down current time to the nearest HH:00 or HH:30 time value
    end_Year=end.year
    end_month=end.month
    end_day=end.day
    end_hour=end.hour
    end_minute=end.minute
    if end_minute<30:end_minute=0
    else:end_minute=30
    end=datetime.combine(date(end_Year,end_month,end_day),time(end_hour,end_minute,0))

    #starting point of the interval
    start=end-timedelta(days=rt_window_length)
    
    #starting point of interval with offset to account for moving window operations 
    offsetstart=end-timedelta(days=rt_window_length+((num_roll_window_ops*roll_window_size-1)/48.))
    
    return end, start, offsetstart

def set_monitoring_window(roll_window_length,data_dt,rt_window_length,num_roll_window_ops):    
    ##INPUT:
    ##roll_window_length; float; length of rolling/moving window operations, in hours
    ##data_dt; float; time interval between data points, in hours    
    ##rt_window_length; float; length of real-time monitoring window, in days
    ##num_roll_window_ops; float; number of rolling window operations in the whole monitoring analysis
    
    ##OUTPUT:
    ##roll_window_numpts; number of data points per rolling window, end; endpoint of interval, 
    ##start; starting point of interval, offsetstart; starting point of interval with offset to account for moving window operations,
    ##monwin; empty dataframe with length of rt_window_length
    
    roll_window_numpts=int(1+roll_window_length/data_dt)
    end, start, offsetstart=get_rt_window(rt_window_length,roll_window_numpts,num_roll_window_ops)
    monwin_time=pd.date_range(start=start, end=end, freq='30Min',name='ts', closed=None)
    monwin=pd.DataFrame(data=np.nan*np.ones(len(monwin_time)), index=monwin_time)

    return roll_window_numpts, end, start, offsetstart, monwin

def uptoDB_gndmeas_alerts(df):
    #INPUT: Dataframe containing all alerts
    #OUTPUT: Writes to sql all ground measurement related alerts database
    engine=create_engine('mysql://root:senslope@192.168.1.102:3306/senslopedb')
    df.to_sql(name = 'gndmeas_alerts', con = engine, if_exists = 'append', schema = Namedb, index = True)

def site_level_alerts_updater(df):
    query = 'UPDATE senslopedb.site_level_alert SET updateTS = "{}" WHERE site = "{}" AND timestamp = "{}" AND source = "{}"'.format(pd.to_datetime(str(df.updateTS.values[0])),df.site.values[0],pd.to_datetime(str(df.timestamp.values[0])),df.source.values[0])
    db, cur = SenslopeDBConnect(Namedb)
    cur.execute(query)
    db.commit()
    db.close()
    
def uptoDB_site_level_alerts(df):
    #INPUT: Dataframe containing site level alerts
    #OUTPUT: Writes to sql database the alerts of sites who recently changed their alert status
    
    #Get the latest site_level_alert
    query = 'SELECT s1.timestamp,s1.site,s1.source,s1.alert, COUNT(*) num FROM senslopedb.site_level_alert s1 JOIN senslopedb.site_level_alert s2 ON s1.site = s2.site AND s1.source = s2.source AND s1.timestamp <= s2.timestamp group by s1.timestamp,s1.site, s1.source HAVING COUNT(*) <= 1 ORDER BY site, source, num desc'
    df2 = GetDBDataFrame(query)
    
    #Merge the two data frames to determine overlaps in alerts
    overlap = pd.merge(df,df2,how = 'left', on = ['site','source','alert'],suffixes=['','_r'])    
    
    #Get the site with no changes in its latest alert
    persistent_alerts = df[~overlap['timestamp_r'].isnull()]
    persistent_alerts['updateTS'] = persistent_alerts['timestamp']
    persistent_alerts['timestamp'] = overlap[~overlap['timestamp_r'].isnull()]['timestamp_r']
    persistent_alerts = persistent_alerts.groupby('site')
    persistent_alerts.apply(site_level_alerts_updater)
    
    #Get the site with change in its latest alert
    changed_alerts = df[overlap['timestamp_r'].isnull()]
    changed_alerts['updateTS'] = changed_alerts['timestamp']
    changed_alerts = changed_alerts[['timestamp','site','source','alert','updateTS']].set_index('timestamp')
    
    engine=create_engine('mysql://root:senslope@192.168.1.102:3306/senslopedb')
    changed_alerts.to_sql(name = 'site_level_alert', con = engine, if_exists = 'append', schema = Namedb, index = True)
    
def get_latest_ground_df(site=None):
    #INPUT: String containing site name    
    #OUTPUT: Dataframe of the last 4 recent ground measurement in the database
    if site == None:
        query = 'SELECT g1.timestamp,g1.site_id,g1.crack_id,g1.meas, COUNT(*) num FROM senslopedb.gndmeas g1 JOIN senslopedb.gndmeas g2 ON g1.site_id = g2.site_id AND g1.crack_id = g2.crack_id AND g1.timestamp <= g2.timestamp group by g1.timestamp,g1.site_id, g1.crack_id HAVING COUNT(*) <= 4 ORDER BY site_id, crack_id, num desc'
    else:
        query = 'SELECT g1.timestamp,g1.site_id,g1.crack_id,g1.meas, COUNT(*) num FROM senslopedb.gndmeas g1 JOIN senslopedb.gndmeas g2 ON g1.site_id = g2.site_id AND g1.crack_id = g2.crack_id AND g1.timestamp <= g2.timestamp group by g1.timestamp,g1.site_id, g1.crack_id HAVING COUNT(*) <= 4 AND site_id = "{}" ORDER BY site_id, crack_id, num desc'.format(site)

    df = GetDBDataFrame(query)
    return df[['timestamp','site_id','crack_id','meas']]

def get_ground_df(start = '',end = '',site=None):
    #INPUT: Optional start time, end time, and site name
    #OUTPUT: Ground measurement data frame

    query = 'SELECT timestamp, site_id, crack_id, meas FROM senslopedb.gndmeas '
    if not start:
        start = '2010-01-01'
    query = query + 'WHERE timestamp > "{}"'.format(start)
    
    if end:
        query = query + ' AND timestamp < "{}"'.format(end)
    if site != None:
        query = query + ' AND site_id = "{}"'.format(site)
    
    return GetDBDataFrame(query)
    
def crack_eval(df,end):
    #INPUT: df containing crack parameters
    #OUTPUT: crack alert according to protocol table
    
    #Obtain the time difference and displacement between the latest values
    if len(df) >= 2:
        time_delta = (df.timestamp.iloc[-1]  - df.timestamp.iloc[-2]) / np.timedelta64(1,'D')
        abs_disp = np.abs(df.meas.iloc[-1]-df.meas.iloc[-2])
        
        crack_alert = 'nd'    
        
        #Based on alert table
        if time_delta >= 7:
            if abs_disp >= 75:
                crack_alert = 'l3'
            elif abs_disp >= 3:
                crack_alert = 'l2'
            else:
                crack_alert = 'l0'
        elif time_delta >= 3:
            if abs_disp >= 30:
                crack_alert = 'l3'
            elif abs_disp >= 1.5:
                crack_alert = 'l2'
            else:
                crack_alert = 'l0'
        elif time_delta >= 1:
            if abs_disp >= 10:
                crack_alert = 'l3'
            elif abs_disp >= 0.5:
                crack_alert = 'l2'
            else:
                crack_alert = 'l0'
        else:
            if abs_disp >= 5:
                crack_alert = 'l3'
            elif abs_disp >= 0.5:
                crack_alert = 'l2'
            else:
                crack_alert = 'l0'
        
        #Perform p value computation for specific crack
        if abs_disp >= 0.5 and abs_disp <= 1:
            if len(df) >= 4:
                #get the last 4 data values for the current feature
                last_cur_feature_measure = df.meas.values
                last_cur_feature_time = (df.timestamp.values - df.timestamp.values[0])/np.timedelta64(1,'D')
    
                #perform linear regression to get p value
                m, b, r, p, std = stats.linregress(last_cur_feature_time,last_cur_feature_measure)
                
                #Evaluate p value
                if p <= 0.05:
                    crack_alert = 'l0p'
    else:
        crack_alert = 'l0'
        
    #Impose the 4 hour validity of the groundmeasurement
    try:
        if end - df.timestamp.iloc[-1] > np.timedelta64(4,'h'):
            crack_alert = 'nd'
    except:
        print 'Timestamp error for '+' '.join(list(np.concatenate((df.site_id.values,df.crack_id.values))))
        crack_alert = 'nd'
    
    return crack_alert

def site_eval(df):
    #INPUT: Dataframe containing crack alerts
    #OUTPUT: Site alert based on the higher perceived risk from the crack alerts, list of cracks that exhibited l2 or l3 alerts, and timestamp

    crack_alerts = df.crack_alerts.values
    if 'l3' in crack_alerts:
        site_alert = 'l3'
    elif 'l2' in crack_alerts:
        site_alert = 'l2'
    elif 'l0p' in crack_alerts:
        site_alert = 'l0p'
    elif 'l0' in crack_alerts:
        site_alert = 'l0'
    else:
        site_alert = 'nd'
    
    #Determine which crack has an l2 or l3 alert
    mask = np.logical_or(crack_alerts == 'l3', crack_alerts == 'l2')
    cracks_to_check = df.crack_id.values[mask]
    
    return pd.Series([site_alert,', '.join(list(cracks_to_check))], index = ['site_alert','cracks_to_check'])

def PlotSite(df,tsn,print_out_path):
    cracks = df.groupby('crack_id')
    site_name = ''.join(list(np.unique(df.site_id.values)))
    plt.figure(figsize = (12,9))
    cracks.agg(PlotCrack)
    plt.xlabel('')
    plt.ylabel(site_name)
    plt.legend(loc='upper left')
    plt.grid(True)
    plt.xticks(rotation = 45)
    plt.savefig(print_out_path+tsn+'_'+site_name,dpi=160, facecolor='w', edgecolor='w',orientation='landscape',mode='w')
    plt.close()

    
def PlotCrack(df):
    disp = df.meas.values
    time = df.timestamp.values
    crack_name = ''.join(list(np.unique(df.crack_id.values)))
    markers = ['x','d','+','s','*']
    plt.plot(time,disp,label = crack_name,marker = markers[df.index[0]%len(markers)])

def GenerateGroundDataAlert(site=None,end=None):
    start_time = datetime.now()
    #Monitoring output directory
    path2 = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    out_path = up_one(up_one(path2)) 
    
    cfg = ConfigParser.ConfigParser()
    cfg.read(path2 + '/server-config.txt')
    
    #Retrieving important declaration files
    printtostdout = True
    output_file_path = cfg.get('I/O','OutputFilePath')
    PrintJSON = cfg.get('I/O','PrintJSON')
    PrintGAlert = cfg.get('I/O','PrintGAlert')
    Namedb = cfg.get('DB I/O','Namedb')
    rt_window_length = cfg.getfloat('I/O','rt_window_length')
    roll_window_length = cfg.getfloat('I/O','roll_window_length')
    data_dt = cfg.getfloat('I/O','data_dt')
    num_roll_window_ops = cfg.getfloat('I/O','num_roll_window_ops')
    
    GrndMeasPlotsPath = cfg.get('I/O','GrndMeasPlotsPath')
    print_out_path = out_path + GrndMeasPlotsPath
    if not os.path.exists(print_out_path):
        os.makedirs(print_out_path)
    
    #Set the monitoring window
    if end == None:
        roll_window_numpts, end, start, offsetstart, monwin = set_monitoring_window(roll_window_length,data_dt,rt_window_length,num_roll_window_ops)
    
#    Use this so set the end time    
#    end = datetime(2016,06,24,12,00,00)

############################################ MAIN ############################################

    #Step 1: Get the ground data from local database 
    df = get_latest_ground_df(site)
    
    #lower caps all site_id names while cracks should be in title form
    df['site_id'] = map(lambda x: x.lower(),df['site_id'])
    df['crack_id'] = map(lambda x: x.title(),df['crack_id'])
    
    #Step 2: Evaluate the alerts per crack
    crack_alerts = df.groupby(['site_id','crack_id']).apply(crack_eval,end).reset_index(name = 'crack_alerts')
    
    #Step 3: Evaluate alerts per site
    site_alerts = crack_alerts.groupby(['site_id']).apply(site_eval).reset_index()    
    
    #Step 4: Include the timestamp of the run, create release ready data frame
    ground_alert_release = site_alerts
    ground_alert_release['timestamp'] = end
    ground_alert_release.columns = ['site','alert','cracks','timestamp']
    ground_alert_release = ground_alert_release.set_index(['timestamp'])
            
    print ground_alert_release
    
    #Step 5: Upload the results to the gndmeas_alerts database
    uptoDB_gndmeas_alerts(ground_alert_release)
    
    #Step 6: Upload to site_level_alert        
    ground_site_level = ground_alert_release.reset_index()
    ground_site_level['source'] = 'ground'
    
    uptoDB_site_level_alerts(ground_site_level[['timestamp','site','source','alert']])
    
    #Step 7: Displacement plot for each crack and site for the last 30 days
    start = end - timedelta(days = 30)
    ground_data_to_plot = get_ground_df(start,end)
    ground_data_to_plot['site_id'] = map(lambda x: x.lower(),ground_data_to_plot['site_id'])
    ground_data_to_plot['crack_id'] = map(lambda x: x.title(),ground_data_to_plot['crack_id'])
    
    tsn=end.strftime("%Y-%m-%d_%H-%M-%S")
    site_data_to_plot = ground_data_to_plot.groupby('site_id')
    site_data_to_plot.apply(PlotSite,tsn,print_out_path)
    
    end_time = datetime.now()
    print "time = ",end_time-start_time
################## #Stand by Functionalities

#    if PrintGAlert:
#        #Creating Monitoring Output directory if it doesn't exist
#        print_out_path = out_path + output_file_path
#        print print_out_path        
#        if not os.path.exists(print_out_path):
#            os.makedirs(print_out_path)
#        
#        print "Ground measurement report as of {}".format(end)
#        print "{:5}: {:5}; Last Date of Measurement; Features to Check".format('Site','Alert')
#        i = 0
#        for site, galert in ground_alert_release:
#            print "{:5}: {:5}; {:24}; {}".format(site,galert[0],str(galert[1]),galert[2])
#            i += 1
#        
#
#        with open (print_out_path+'groundalert.txt', 'w') as t:
#            i = 0
#            t.write("Ground measurement report as of {}".format(end)+'\n')
#            t.write("{:5}: {:5}; Last Date of Measurement; Features to Check".format('Site','Alert')+'\n')
#            for site, galert in ground_alert_release:
#                t.write ("{:5}: {:5}; {:25}; {}".format(site,galert[0],str(galert[1]),galert[2])+'\n')
#                i += 1

#    if PrintJSON:        
#        #converting the data frame to JSON format
#        dfajson = ground_alert_release.to_json(orient="records",date_format='iso')
#        
#        #ensuring proper datetime format
#        i = 0
#        while i <= len(dfajson):
#            if dfajson[i:i+9] == 'timestamp':
#                dfajson = dfajson[:i] + dfajson[i:i+36].replace("T"," ").replace("Z","").replace(".000","") + dfajson[i+36:]
#                i += 1
#            else:
#                i += 1
#        print dfajson
#    print dfa[['alert_timestamp','site_id','g alert','features to check']].set_index(['alert_timestamp'])
#    uptoDB(dfa[['alert_timestamp','site_id','g alert','features to check']].set_index(['alert_timestamp']))
