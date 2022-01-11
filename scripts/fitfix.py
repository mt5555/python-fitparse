#!/usr/bin/env python
import fitparse
import mmap
import datetime
import os
#import pyproj
#import geopy
from math import sqrt,sin,cos,pi,atan2

from fitparse.records import ( Crc  )
#
# to run:
# setenv PYTHONPATH /Users/mt/misc/garmin66i/python-fitparse
# processed fit file will be in new.fit
#
# TODO:
#  use pyproj or geopy to compute better distance (more accurate Rearth)
#  command line to specify badjump and badjump_t
#  command line option to disable updating totaltime and duration
#
#

# end-of-trip trim specified in UTC
# use FitFileExplorer to find date to start trim (will be in local timezone)
# look at "activity" record to get UTC offset:
#   local_timestamp:  8:19AM
#   timestamp:        2:19PM          delta=6h
# add 6h from track time to convert to UTC needed below:
#
#trim_after_utc="2021-06-21:17:13:28"  # baldy backpack trip + 6H
trim_after_utc="2099-06-21:11:13:28"   # distable trim

# remove anything before this date:
# my garmin 66i was producing a lot of 2019 timestamps in 2020.
# hopefully fixed with latest firmware
baddate = "2020-01-01"

# remove jumps greater than "badjump" if they took badjump_t seconds
badjump = 450.0
#badjump = 110.0  # used for heaven hill trip
badjump_t = 15*60  # allow jumps if gap is more than 15min
                   # so if there is a sequence of bad points, when they eventually
                   # get back on track, there could be a large gap from last good point
                   # this will get back on track after 15min no matter what
                   # another option: once "bad", then wait for next jump, assume
                   # next jump is back to a good point.  
bad_d1=datetime.datetime.fromisoformat(baddate)
trim_d1=datetime.datetime.fromisoformat(trim_after_utc)


fname=os.sys.argv[1]
fitfile = fitparse.FitFile(fname)
basename=fname.split("/")[-1]
#fnameout=fname.split(".fit")[0] + "-pyfixed.fit"
fnameout="/tmp/"+fname.split(".fit")[0] + "-pyfixed.fit"
print("input:  ",fname)
print("output: ",fnameout)

fin=open(fname,"r+b")
mm = mmap.mmap(fin.fileno(), 0)
fout=open(fnameout,"w+b")


# Iterate over all messages of all types
# (types include "record", "device_info", "file_creator", "event", etc)
#rad_to_deg=360./(2*pi)
deg_to_rad=2*pi/360.
iprev=0
foutsize=0
dist_between_records = -1.0
dist_tot=0

time_min=datetime.datetime.fromisoformat("2100-01-01")
time_max=datetime.datetime.fromisoformat("1900-01-01")

update_totals=False
delete_badtime=0
delete_trim=0
delete_jump=0
#for record in fitfile.get_messages("record"):
for record in fitfile.get_messages(None):
    ni=len(fitfile.recpos)-1
    print("[",fitfile.recpos[ni-1]+1,":",fitfile.recpos[ni],"]",record.name,record.type)
    # Records can contain multiple pieces of data (ex: timestamp, latitude, longitude, etc)
    delete=False
    latlon_count=0
    for data in record:
        # Print the name and value of the data (and the units if it has any)
        if data.units:
            #if data.name[:6]=="total_" and record.name=='session':
            #    print(data.name,data.value)
            if data.name=="total_distance" and record.name=='session':
                session_dist_tot=data.value
            if data.name=="total_elapsed_time" and record.name=='session':
                session_total_elapsed_time=data.value
            if data.name[:9]=="position_" and record.name=="record":
                if data.value is not None:
                    data.value *= 180.0 / (2**31)
                    data.units = 'deg'
                    if data.name=="position_lat":
                        lat2 = data.value*deg_to_rad
                        latlon_count += 1
                    if data.name=="position_long":
                        lon2 = data.value*deg_to_rad
                        latlon_count += 1
                    print(" * {}: {} ({})".format(data.name, data.value, data.units))
        else:
            if data.name=="timestamp"  and record.name=="record":
                t2=data.value
                # trim bad timesteps, but only from records, not other events
                if data.value<bad_d1:
                    delete=True
                    delete_badtime +=1
                    print(" * REMOVE: {}: {}".format(data.name, data.value))
                if data.value>trim_d1:
                    delete=True
                    delete_trim +=1
                    print(" * TRIMMING: {}: {}".format(data.name, data.value))
                else:
                    print(" * {}: {}".format(data.name, data.value))
                    
    if (not delete) and latlon_count==2 and record.name=="record":
        time_min=min(time_min,t2)  # compute min/max over all valid timestamps with coordinate info
        time_max=max(time_max,t2)  # other records have timestamps that dont line up (maybe UTC instead of MT?
        if dist_between_records<0:
            # first coordinates. initialize lat1,lon1,t1
            dist_between_records=0
            lat1=lat2
            lon1=lon2
            t1=t2
        else:
            # compute distance
            #
            #  python packages to compute geod distance:
            #     https://janakiev.com/blog/gps-points-distance-python/
            #
            #
            dlon = lon2-lon1
            dlat = lat2-lat1
            a=sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            dist_between_records= 2*sqrt(a)  # chord
            #dist_between_records= 2*atan2(sqrt(a),sqrt(1-a))  # great circle (diff in 13 digit for hike)
            dist_between_records *= 6378.1*1000  # convert to meters
            
            time_between_records = (t2-t1).total_seconds()
            speed=dist_between_records/time_between_records  # m/s
            speed *= 60*60/1000  # km/hour
            if (dist_between_records > badjump and time_between_records < badjump_t ):
                print(" * REMOVE dist(meters): ",dist_between_records,t2-t1,speed)
                # bad point. delete it, and dont reset lat1,lon1
                if delete==False:
                    delete_jump += 1  # dont count if we were already deleted for bad time
                delete=True
            else:
                print(" * dx(m):",'{:0.2f}'.format(dist_between_records),
                      "dt:",(t2-t1),"v(m/s)=",'{:.2f}'.format(speed))
                dist_tot += dist_between_records
                lat1=lat2
                lon1=lon2
                t1=t2

    if delete and latlon_count==2:
        # we are deleting a record with coordinate info, so update route length and duration
        update_totals=True        

    if delete:
        inext=fitfile.recpos[-2]
    else:
        inext=fitfile.recpos[-1]

    if (inext>iprev):
        datacopy=bytearray(mm[iprev:inext])

        if (record.name=='lap' or record.name=='session') and update_totals:
            print(" * editing lap/session record:")
            data = next(data for data in record if data.name=="total_distance")
            if (data.name=="total_distance"):
                start=data.filepos-iprev
                dsize=data.field_def.size
                data_raw=int.from_bytes(datacopy[start:(start+dsize)], "little",signed=False)
                data_raw_new=int(round(dist_tot*100))
                print(" *   {}: {} ({}) pos={} size={} data={}".format(data.name, data.value, data.units,start,dsize,data_raw))
                print(" *   to be repalced by: 100*",dist_tot,"=",data_raw_new)
                data_new_bytes=data_raw_new.to_bytes(dsize,'little')
                datacopy[start:(start+dsize)] = data_new_bytes[0:dsize]
                #data_raw=int.from_bytes(datacopy[start:(start+dsize)], "little",signed=False)
                #print(" *   new data_raw=",data_raw)
            data = next(data for data in record if data.name=="total_elapsed_time")
            if (data.name=="total_elapsed_time"):
                start=data.filepos-iprev
                dsize=data.field_def.size
                data_raw=int.from_bytes(datacopy[start:(start+dsize)], "little",signed=False)
                data_new=(time_max-time_min).total_seconds()
                data_raw_new=int(round(data_new*1000))
                print(" *   {}: {} ({}) pos={} size={} data={}".format(data.name, data.value, data.units,start,dsize,data_raw))
                print(" *   to be repalced by: 100*",data_new,"=",data_raw_new)
                data_raw_new=min(data_raw_new,(2**(8*dsize-1)))
                data_new_bytes=data_raw_new.to_bytes(dsize,'little')
                datacopy[start:(start+dsize)] = data_new_bytes[0:dsize]
                

        fout.write(datacopy)
        foutsize += len(datacopy)
        
    iprev=fitfile.recpos[-1]

    


# write final records:
fout.write(mm[ iprev : fitfile.recpos[-1] ])
foutsize += fitfile.recpos[-1]-iprev
fout.flush()

# fix header and CRC info in new file:
mmout = mmap.mmap(fout.fileno(), 0)

hsize = int.from_bytes(mmout[4:8], "little", signed=False)
hcrc  = (fitfile._filesize-hsize)
# fix filesize in header:
out_hsize=foutsize-hcrc
mmout[4:8]=out_hsize.to_bytes(4,'little')

# fix header and final CRC:
headerCRC=Crc()
headerCRC.update(mmout[0:12])
mmout[12:14]=headerCRC.value.to_bytes(2,'little')

headerCRC.value=0
headerCRC.update(mmout[0:foutsize-2])
mmout[-2:]=headerCRC.value.to_bytes(2,'little')

    



print("original filesize = ",fitfile._filesize,len(mm))
print("new file: bytes written, filesize = ",foutsize,len(mmout))
print("Total distance (original, computed):",0.621371*session_dist_tot/1000,
      0.621371*dist_tot/1000,"mi")
print("start/stop: ",time_min,"to",time_max)
print("Elapsed time (original, computed):",session_total_elapsed_time,
      (time_max-time_min).total_seconds(),"s")
print("Records deleted for timestamp<",baddate,"=",delete_badtime)
print("Records deleted for timestamp>",trim_after_utc,"=",delete_trim)
print("Records deleted for jump(m)  >",badjump,"=",delete_jump)
print("Output file: ",fnameout)






