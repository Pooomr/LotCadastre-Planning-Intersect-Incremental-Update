''' Update Lot_Zone table Proof of Concept
	v1 - First version - Select records based on last_update_date filter working
	v1a - Unable to make tabulation work with lot layer (no OID)
	v2 - New version, processes Zones in 30 day chunks
'''

import logging
import sys

username = sys.argv[1]

#Logging settings
logger = logging.getLogger("LotPlanningLog")
logger.setLevel(logging.DEBUG)					
file_handler = logging.FileHandler('log.txt')
formatter = logging.Formatter("%(asctime)s - {} - %(message)s".format(username),'%d/%m/%Y %H:%M:%S')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

logger.debug("Importing Python Packages...")
logger.info("[START] Lot_Zone Update process started")

try:
	import arcpy
except:
	print("Error Importing arcpy module, make sure OpenVPN is connected and licences are available!")
	logger.info("[STOPPED] Unable to import arcpy module, Lot Planning update Stopped")
	sys.exit()

import os
from arcpy import env
import pandas as pd
from datetime import datetime, timedelta
import config
import cx_Oracle
import requests
import json

current_update = datetime.now()

logger.debug("Python packages imported successfully")

def loadingBar(p: int, msg: str) -> str:
	
	progress = ""
	togo = "          "
	
	togo = togo[:-p] #reduce empty space based on progress
	
	for i in range(p):
		progress += "■"
		
	
	print("[{}{}] {}                            ".format(progress, togo, msg), end="\r")

def getNextId(column: str, table: str) -> int:
	c.execute("select max({}) from {}".format(column, table))
	result = c.fetchone()
	
	#If records exist, increment next id, else start at 1
	if result[0] != None:
		nextId = result[0] + 1
	else:
		nextId = 1
	
	return nextId

def createSession(username,password):
	#Creates Session Connection pool to GPR Database

	oc_attempts = 0

	while oc_attempts < 2:
		if oc_attempts == 0:
			print("Trying DPE IP: {}".format(config.dsnDPE))
			dsn = config.dsnDPE
		else:
			dsn = config.dsnDCS
			print("Trying DCS IP: {}".format(config.dsnDCS))
			
		try:
			pool = cx_Oracle.SessionPool(
				username,
				password,
				dsn,
				min=1,
				max=3,
				increment=1,
				encoding=config.encoding)

			# show the version of the Oracle Database
			print("Connection Successful!")
			oc_attempts = 2
		except cx_Oracle.Error as error:
			logger.info("[ERROR] {}".format(error))
			print(error)
			oc_attempts += 1
			
	return pool
	
def getRESTData(baseURL, params, serviceName):
	
	retries = 0
	success = False
	r_code = 0
	response = None
	
	while not success:
		try:
			#response = requests.get(url=baseURL, params=params, verify=False)
			response = requests.get(url=baseURL, params=params)
			success = True
		except requests.exceptions.RequestException as e:
			print(e)
			retries += 1
			if retries > 9:
				while True:
					select = input("\nRequest to {} service failed 10 times, Do you want to try again? y/n\n".format(serviceName))
					if select == "y":
						retries = 0
						break
					elif select == "n":
						print("Lot Zoning update process Aborted!!")
						sys.exit()
					else:
						print("Invalid selection. Please enter y or n")
		
		if response:
			r_code = response.status_code
		else:
			r_code = 0
		
		while r_code != 200 and success:
			print("Response code: {}".format(response.status_code))
			select2 = input("\nInvalid response received, run query again? y/n\n")
			if select2 == "y":
				retries = 0
				success = False
				break
			elif select2 == "n":
				print("Lot Zoning update process Aborted!!")
				logger.info("Lot Zoning update aborted by User")
				sys.exit()
			else:
				print("Invalid selection. Please enter y or n")
	#logger.debug("REST response for: {}".format(baseURL))
	#logger.debug("Params are {}".format(params))
	#logger.debug("Results are {}".format(response.text))
	return json.loads(response.text)
	
def createLotLayer(zoneId,baseURL):
	#Creates Lot feature layer via JSON results
	df_lots = pd.read_sql("select distinct lotref from LZ_LOT_SPATIAL where lz_update_log_id = {}".format(zoneId),connection)
	
	#logger.debug("Running createLotLayer: df_lots contains {}".format(df_lots))
	
	#Temporary JSON file
	tempJSON = "{}\\arcGIS\\Temp.json".format(os.getcwd())
	
	#JSON Head for Lots
	JSONHead = '{"displayFieldName": "planlabel","fieldAliases": {"lotidstring":"lotidstring" },"geometryType": "esriGeometryPolygon","spatialReference": {"wkid": 4326,"latestWkid": 4326},"fields": [{"name":"lotidstring","type":"esriFieldTypeString","alias":"lotidstring","length":50} ],"features": ['
	
	#initialise string to pass through Lot Cadastre query
	lotstring = ''
	
	#Initialise List to store all Json results
	lotResults = list()
	
	for i, row in df_lots.iterrows():
		if lotstring == '':
			lotstring += "'{}'".format(row["LOTREF"])
		else:
			lotstring += ",'{}'".format(row["LOTREF"])
		
		#Every 200 records query service
		if (i + 1) % 200 == 0 or (i + 1) == len(df_lots):
			
			params = {
				'f':'json',
				'returnGeometry':'true',
				'outSR':'4326',
				'OutFields':'lotidstring',
				'where':'lotidstring in ({})'.format(lotstring)
			}
			
			#TO-DO ADD RETRY MECHANISM FOR EMPTY RESULTS
			jsonResult = getRESTData(baseURL, params, "Lot Service")
					
			if jsonResult.get('features'):
				#iterate through all features in JSON response and add to Result list
				for jr in range(len(jsonResult['features'])):
					lotResults.append(jsonResult['features'][jr])
			else:
				print("ERROR: {}".format(jsonResult))
				logger.debug("ERROR in create Lot Layer: {}".format(jsonResult))
				
			lotstring = ''
			
	#If Scratch folder doesn't exist, create it
	if not os.path.exists("{}\\arcGIS\\scratch.gdb".format(os.getcwd())):
		arcpy.management.CreateFileGDB("{}\\arcGIS".format(os.getcwd()), "scratch.gdb")
		logger.debug("Scratch folder created...")
	
	writeToJSON(JSONHead, tempJSON, lotResults, 'lots_to_update')

def writeToJSON(JSONHead, tempJSON, JSONResults, layerName):
	
	JSONinput = ""
	JSONinput += "{}".format(JSONHead)
	totalSLots = len(JSONResults)
	fileNum = 1
	
	#logger.debug("Running writeToJSON: JSONResults is {}".format(JSONResults))
	
	logger.debug("WRITING TO JSON... {}".format(totalSLots))
	for i, row in enumerate(JSONResults):
		
		#Add lot records to JSON
		if (i + 1) % 3000 == 1:
			JSONinput += '{}'.format(JSONResults[i]) #If first record do not add comma
		else:
			JSONinput += ',{}'.format(JSONResults[i])
		
		#If max range met, close file and open new one
		if (i + 1) % 3000 == 0 or (i + 1) == totalSLots:
			JSONinput += ']}'
			logger.debug("Writing to JSON file at {}".format(tempJSON))
			#Clear Temp JSON file and insert results
			with open(tempJSON,'w') as jsonDir:
				jsonDir.write(JSONinput.replace("None","null")) #Replace instances of 'None' with null
			
			logger.debug("Writing to scratch arcGIS project folder...")
			#Load to arcGIS folder
			arcpy.conversion.JSONToFeatures(tempJSON,"{}\\arcGIS\\scratch.gdb\\{}_{}".format(os.getcwd(),layerName, fileNum),"POLYGON")
			
			fileNum += 1
			JSONinput = "{}".format(JSONHead) #Reset
			
	#Merge all scratch files
	LayerList = ''
	logger.debug("Merge {} files".format(fileNum - 1))
	for layer in range(1, fileNum):
		logger.debug("processing {} of {}".format(layer, fileNum - 1))
		if layer == 1:
			LayerList += "{}\\arcGIS\\scratch.gdb\\{}_{}".format(os.getcwd(),layerName,layer)
		else:
			LayerList += ";{}\\arcGIS\\scratch.gdb\\{}_{}".format(os.getcwd(),layerName,layer)
	logger.debug("Run: Merge({},{})".format(LayerList,"{}\\arcGIS\\lot_zone_update.gdb\\{}".format(os.getcwd(),layerName)))	
	arcpy.management.Merge(LayerList, "{}\\arcGIS\\lot_zone_update.gdb\\{}".format(os.getcwd(),layerName))

def extractLots(lzId, totalRec):
	#Go through Zone BBOXs and extract lots
	print("GOING THROUGH ZONES TO EXTRACT LOTS")
	
	geoInput = '' #Initialise string for coordinates
	oIDInput = '' #Initialise string for Lot Object Ids
	lots = list() #Store lots that intersect with zone layers
			
	df_bbox = pd.read_sql("select lz_zone_bbox_id, lz_update_log_id, spatial_ref, bbox from LZ_ZONE_BBOX where lz_update_log_id = {} and processed is null".format(lzId),connection)
	print(df_bbox)
	count = 0
	lcount = 0
	
	for index, row in df_bbox.iterrows():
		sRef = row["SPATIAL_REF"]
		if geoInput == '':
			geoInput = "{}".format(row["BBOX"])
		else:
			geoInput += ",{}".format(row["BBOX"])
		
		count += 1
		logger.debug("geoInput is {}".format(geoInput))
		logger.debug("count is {} ({}) - zoneShp is {} - TotalRecords is {} ({})".format(count,type(count),zoneShp,totalRec,type(totalRec)))
		logger.debug("sRef is {}".format(sRef))
		logger.debug("count % zoneShp = {}".format(count % zoneShp))
		logger.debug("count == totalRecords is {}".format(count == totalRec))
		if count % zoneShp == 0 or count == totalRec:
			params = {
				'f':'json',
				'outFields':'objectid',
				'returnGeometry':'false',
				'inSR':sRef,
				'returnIdsOnly':'true',
				'geometry':'{{"rings":[{}]}}'.format(geoInput),
				'geometryType':'esriGeometryPolygon',
				'spatialRel': 'esriSpatialRelIntersects'
			}
			# TO-DO: ADD RETRY MECHANISM, AND HANDLER FOR EMPTY RESULTS
			retries_1 = 0
			success_1 = False
			
			while not success_1:
				jsonResult = getRESTData(LotUrl, params, "Lot Cadastre Service")
				logger.debug("Getting lots in Zone BBOX: {}".format(jsonResult))
				#Delay calls to rest service
				time.sleep(2)
				
				#Iterate through ObjectIDs and extract lot information
				if jsonResult.get('objectIds'):
					for oID in jsonResult['objectIds']:
						
						if oIDInput == '':
							oIDInput = '{}'.format(oID)
						else:
							oIDInput += ",{}".format(oID)
						
						lcount += 1
						
						if lcount % lotLimit == 0 or lcount == len(jsonResult['objectIds']):
							params = {
								'f':'json',
								'outFields':'lotidstring',
								'returnGeometry':'false',
								'returnDistinctValues':'true',
								'where':'objectid in ({})'.format(oIDInput)
							}
							jsonLotResult = getRESTData(LotUrl, params, "Lot Cadastre Service")
							
							if jsonLotResult.get('features'):
								success_1 = True
								for lotref in jsonLotResult["features"]:
									#build up list of lots to insert
									lots.append(lotref["attributes"]["lotidstring"])
							else:
								retries += 1
								print("ERROR: {}".format(jsonLotResult))
								logging.info("[ERROR] Results do not contain features, retrying.. {}".format(jsonLotResult))
							
							oIDInput = '' #Reset
				else:
					retries_1 += 1
					print("ERROR: {}".format(jsonResult))
					logging.info("[ERROR] Results do not contain objectIds, retrying.. {}".format(jsonResult))
				
				#If REST calls were successful, insert into table
				if success_1:
					#All Lots extracted, insert into table
					query = "insert all "
					#c.execute("select max(lz_lot_spatial_id) from LZ_LOT_SPATIAL")
					
					#Set next LZ_LOT_SPATIAL_ID
					nextLsId = getNextId("LZ_LOT_SPATIAL_ID","LZ_LOT_SPATIAL")
						
					for i, lotref in enumerate(lots):
						query = "{} into LZ_LOT_SPATIAL values ({}, {}, '{}', CURRENT_TIMESTAMP, null)".format(query,nextLsId,lzId,lotref)
						nextLsId += 1
						
						if (i + 1) % 1000 == 0 or (i + 1) == len(lots):
							query = "{} select 1 from dual".format(query)

							try:
								c.execute(query)
							except cx_Oracle.Error as error:
								logger.info("[ERROR] {}".format(error))
								print(error)
							
							query = "insert all "
					
					geoInput = ''
				else:
					#Issue with REST Call, retry
					while retries_1 > 9:
						select = input("\nResults from Lot Service are incorrect and failed 10 times, Do you want to try again? y/n\n")
						if select == "y":
							retries_1 = 0
							break
						elif select == "n":
							print("Lot Zoning update process Aborted!!")
							logger.info("[EXIT] Lot Zone Update process aborted by user")
							sys.exit()
						else:
							print("Invalid selection. Please enter y or n")
							
	c.execute("commit")
	
def intersectLotZone(lzId,layerName):
	#Tabulate Intersect Lot Layer with current Zone layer
	arcpy.analysis.TabulateIntersection("{}\\lots_to_update".format(arcFolder), "lotidstring", ZoningLayer, "{}\\{}".format(arcFolder,layerName), "EPI_NAME;EPI_TYPE;SYM_CODE;LAY_CLASS", None, "10 Centimeters", "SQUARE_METERS")
	logger.debug("{}\\lots_to_update".format(arcFolder))
	logger.debug(ZoningLayer)
	logger.debug("{}\\{}".format(arcFolder,layerName))
	
	# c.execute("update LZ_UPDATE_LOG set finish_date = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(lzId))
	# c.execute("update LZ_LOT_SPATIAL set processed = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(lzId))
	# c.execute("commit")
	
	logger.info("[PROCESS] Tabulate Intersection complete for lz_update_log_id: {}".format(lzId))

def updateLotZone():
	#Update Lot_Zone table
	fieldNames = ["OBJECTID","lotidstring","EPI_NAME","EPI_TYPE","SYM_CODE","LAY_CLASS","AREA","PERCENTAGE"]
	with arcpy.da.SearchCursor("{}\\Lot_Zone_to_update".format(arcFolder),fieldNames) as cur:
		for row in cur:
			print("{} {} {} {} {}".format(row[1],row[2],row[3],row[4]))
			
if __name__ == "__main__":
	
	# Connect to DB and create session pool
	try:
		pool = createSession(config.username, config.password)
	except RuntimeError as e:
		logger.error(str(e))
		print(str(e))
		sys.exit(1)

	# Acquire connection from the pool
	connection = pool.acquire()
	c = connection.cursor()
	
	#Connection files
	ZoningLayer = "{}\\arcGIS\\PlanningSDE.sde\\PlanningDB.SDE.EPI\\PlanningDB.SDE.EPI_Land_Zoning".format(os.getcwd())
	LotLayer = "{}\\arcGIS\\DCDB_SDE.sde\\DCDB_DELIVERY.sde.LotAll".format(os.getcwd())
	LotUrl = "https://maps.six.nsw.gov.au/arcgis/rest/services/sixmaps/Cadastre/MapServer/0/query"
	
	#ArcPy Settings
	logger.debug("[DEBUG] Setting up ArcGIS connection to Planning SDE")
	env.overwriteOutput = True
	arcFolder = "{}\\arcGIS\\lot_zone_update.gdb".format(os.getcwd())
	LZ_to_update = "{}\\LandZoning_to_update".format(arcFolder)
	logger.debug("[DEBUG] Connected to Planning SDE")
	
	#SET LIMITS
	zoneShp = 5 #Total number of zones to extract lots each round
	lotLimit = 200 #Total number of lots to query each round
	
	#Check if there are unprocessed lots
	df_lz_to_process = pd.read_sql("select distinct lz_update_log_id from LZ_LOT_SPATIAL where processed is null order by lz_update_log_id",connection)
	if len(df_lz_to_process) > 0:
		for i, to_proc in df_lz_to_process.iterrows():
			logger.info("[PROCESS] Continued processing lots for lz_update_log_id: {}".format(to_proc["LZ_UPDATE_LOG_ID"]))
			createLotLayer(to_proc["LZ_UPDATE_LOG_ID"],LotUrl)
			
			intersectLotZone(to_proc["LZ_UPDATE_LOG_ID"],"Lot_Zone_to_update")
			
			#Update Log and Lot records as complete
			c.execute("update LZ_UPDATE_LOG set finish_date = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(to_proc["LZ_UPDATE_LOG_ID"])) #Update Lot Zone Log to indicate zone is complete
			c.execute("update LZ_LOT_SPATIAL set processed = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(to_proc["LZ_UPDATE_LOG_ID"]))
			c.execute("commit")
	
	#Check if there are unprocessed Zones (to get list of lots from)
	df_zone_to_process = pd.read_sql("select lz_update_log_id, count(*) total_records from LZ_ZONE_BBOX where processed is null group by lz_update_log_id order by lz_update_log_id",connection)
	if len(df_zone_to_process) > 0:
		for i, to_proc in df_zone_to_process.iterrows():
			logger.info("[PROCESS] Continued processing Zones for lz_update_log_id: {}".format(to_proc["LZ_UPDATE_LOG_ID"]))
			
			extractLots(to_proc["LZ_UPDATE_LOG_ID"],int(to_proc["TOTAL_RECORDS"]))
			
			createLotLayer(to_proc["LZ_UPDATE_LOG_ID"],LotUrl)
			
			intersectLotZone(to_proc["LZ_UPDATE_LOG_ID"],"Lot_Zone_to_update")
			
			#Update Zones as complete
			c.execute("update LZ_ZONE_BBOX set processed = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(to_proc["LZ_UPDATE_LOG_ID"]))
			c.execute("commit")
			
	#Get last update date of Lot_Zone
	c.execute("select max(end_date) from LZ_UPDATE_LOG where finish_date is not null")
	last_update_tuple = c.fetchone()

	if last_update_tuple[0]:
		last_update = last_update_tuple[0] #Found the last updated Lot Zone phase
		logger.info("[PROCESS] Last Lot Zone log update found: {}".format(last_update))
	else:
		c.execute("select max(update_date) from lot_zone") #No Lot Zone Logs found, use last updated Lot_zone record instead
		last_update_tuple = c.fetchone()
		
		if last_update_tuple[0]:
			last_update = last_update_tuple[0]
			logger.info("[PROCESS] Last Lot Zone log update not found, using last lot_zone update instead: {}".format(last_update))
		else:
			logger.info("[ERROR] Unable to obtain 'last_update' from lot_zone, please check data source")
			print("Unable to retrieve 'last_update' from lot_zone table")
			sys.exit()
	print("LAST UPDATE IS {}".format(last_update))

	c.close()
	pool.release(connection)
	
	#Set current date
	current_date = datetime.today()
	end_period = last_update + timedelta(days=30) #Get Zoning updates in 30 day chunks
	
	print("Test Selection...")
	logger.info("[INFO] Selecting records")
	
	print("{}".format(last_update.strftime('%Y-%m-%d %H:%M:%S')))
	
	#Iterate through all Updated Zone layers until done
	while last_update < current_date:
	
		#Set Date Range for Zone selection
		date_range_expression = "LAST_EDITED_DATE >= '{}' AND LAST_EDITED_DATE < '{}'".format(last_update.strftime('%Y-%m-%d %H:%M:%S'),end_period.strftime('%Y-%m-%d %H:%M:%S'))
		
		#Copy updated records to new layer 'LandZoning_to_update'
		#arcpy.Select_analysis(ZoningLayer, "{}\\LandZoning_to_update".format(arcFolder), where_clause=date_range_expression)
		
		totalRecords = int(arcpy.management.GetCount(LZ_to_update)[0]) #Total Zone records to iterate
		
		#Insert lz_update_log record and get ID
		connection = pool.acquire() #Acquire connection from pool
		c = connection.cursor()
		
		c.execute("insert into LZ_UPDATE_LOG values (SEQ_LZ_UPDATE_LOG.nextval, TO_DATE('{}', 'yyyy/mm/dd hh24:mi:ss'), TO_DATE('{}', 'yyyy/mm/dd hh24:mi:ss'), CURRENT_TIMESTAMP, null, {}, '{}')".format(last_update.strftime('%Y/%m/%d %H:%M:%S'),end_period.strftime('%Y/%m/%d %H:%M:%S'),totalRecords,username))
		c.execute("commit")
		c.execute("SELECT SEQ_LZ_UPDATE_LOG.currval FROM dual")
		lz_update_log_id = c.fetchone()[0]
		
		#Store all Zone Bounding Boxes
		if totalRecords > 0:
			nextBiD = getNextId("LZ_ZONE_BBOX_ID","LZ_ZONE_BBOX")
			with arcpy.da.SearchCursor(LZ_to_update,['OID@','SHAPE@','EPI_NAME','LAY_CLASS','SYM_CODE']) as cursor:
				logger.debug("Storing Zone BBOX...")
				zcount = 0
				query = "insert all "
				for row in cursor:
					zoneInfo = "{}|{}|{}".format(row[2],row[3],row[4])
					sRef = row[1].extent.spatialReference.factoryCode
					bbox = '[[{},{}],[{},{}],[{},{}],[{},{}],[{},{}]]'.format(row[1].extent.XMin,row[1].extent.YMin,row[1].extent.XMax,row[1].extent.YMin,row[1].extent.XMax,row[1].extent.YMax,row[1].extent.XMin,row[1].extent.YMax,row[1].extent.XMin,row[1].extent.YMin)
					
					query = "{} into LZ_ZONE_BBOX (LZ_ZONE_BBOX_ID, LZ_UPDATE_LOG_ID, LZ_ZONE_OID, LZ_ZONE_INFO, SPATIAL_REF, BBOX) values ({},{},{},'{}','{}','{}')".format(query,nextBiD,lz_update_log_id,row[0],zoneInfo,sRef,bbox)
					
					zcount += 1
					nextBiD += 1
					
					if zcount % 1000 == 0 or zcount == totalRecords:
						#Insert records every 1000
						query = "{} select 1 from dual".format(query)
						print(query)
						try:
							c.execute(query)
						except cx_Oracle.Error as error:
							logger.info("[ERROR] {}".format(error))
							print(error)
						
						query = "insert all "
			c.execute("commit")
			logger.debug("Inserted {} Zoning records".format(zcount))
			
		print("Last inserted ID:", lz_update_log_id)
		
		count = 0 #Keep track of record count
		lcount = 0 #Keep track of lot count
		#TO-DO CHANGE TO ITERATE THROUGH BBOX RECORDS TO EXTRACT LOTS
		if totalRecords > 0:
			#GET LOTS FOR EACH ZONE SHAPE
			
			logger.info("[PROCESS] Processing Zones for {} -> {}".format(last_update, end_period))
			print("[PROCESS] Processing Zones for {} -> {}".format(last_update, end_period))
			logger.debug("Total records are {}".format(totalRecords))
			
			#Go through each record in LandZoning_to_update and find intersected lots
			logger.debug("Going through Zone layers...")
			extractLots(lz_update_log_id, totalRecords)
			
			#TO-DO ADD HANDLER TO CHECK FOR EMPTY LOT RESULTS FROM PREVIOUS STEP
			#Create Lot Spatial Layer
			logger.info("[PROCESS] Processing lots for lz_update_log_id: {}".format(lz_update_log_id))
			createLotLayer(lz_update_log_id,LotUrl)
			
			#Tabulate Intersect Lot layer with current Zone layer
			intersectLotZone(lz_update_log_id,"Lot_Zone_to_update")
			
			#Process Intersected Results
			updateLotZone()
		
		logger.info("[PROCESS] {} Lots Intersected for {} Zones".format(lcount,count))
		print("{} Lots identified for {} Zones".format(lcount,count))
		
		#Update Log and Lot records as complete
		c.execute("update LZ_UPDATE_LOG set finish_date = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(lz_update_log_id)) #Update Lot Zone Log to indicate zone is complete
		c.execute("update LZ_LOT_SPATIAL set processed = CURRENT_TIMESTAMP where lz_update_log_id = {}".format(lz_update_log_id))
		c.execute("commit")
		
		c.close()
		pool.release(connection)
		
		#Finished Zoning chunk, set up for next 30 days
		last_update = end_period
		end_period = end_period + timedelta(days=30) #set up next chucnk
		
		
		print("Last_update: {}".format(last_update))
	
	logger.info("[FINISH] Lot_Zone Update process finished")
	print("Done!")