#!/bin/csh -f
#set echo
echo `date`   
# SET INPUTS
setenv BATCHRUN $1
shift
setenv ENVIRONMENT $1 
shift

if ( "$BATCHRUN" != "0" ) then

	set xmltest=`echo $ENVIRONMENT | rev | cut -c -4 | rev`
	if ( "$xmltest" == ".xml" ) then
		source /group/halld/Software/build_scripts/gluex_env_jlab.csh $ENVIRONMENT
	else
		source $ENVIRONMENT
	endif

endif

setenv ANAENVIRONMENT $1 
shift
setenv CONFIG_FILE $1
shift
setenv OUTDIR $1
shift
setenv RUN_NUMBER $1
shift
setenv FILE_NUMBER $1
shift
setenv EVT_TO_GEN $1
shift
setenv VERSION $1
shift
setenv CALIBTIME $1
set wholecontext = $VERSION
if ( "$CALIBTIME" != "notime" ) then
set wholecontext = "variation=$VERSION calibtime=$CALIBTIME"
else
set wholecontext = "variation=$VERSION"
endif
setenv JANA_CALIB_CONTEXT "$wholecontext"
shift
setenv GENR $1
shift
setenv GEANT $1
shift
setenv SMEAR $1
shift
setenv RECON $1
shift
setenv CLEANGENR $1
shift
setenv CLEANGEANT $1
shift
setenv CLEANSMEAR $1
shift
setenv CLEANRECON $1
shift
setenv BATCHSYS $1
shift
setenv NUMTHREADS $1
shift
setenv GENERATOR $1
shift
setenv GEANTVER $1
shift
setenv BKGFOLDSTR $1
shift
setenv CUSTOM_GCONTROL $1
shift
setenv eBEAM_ENERGY $1
shift
setenv COHERENT_PEAK $1
shift
setenv GEN_MIN_ENERGY $1
shift
setenv GEN_MAX_ENERGY $1
shift
setenv TAGSTR $1
shift
setenv CUSTOM_PLUGINS $1
shift
setenv PER_FILE $1
shift
setenv RUNNING_DIR $1
shift
setenv ccdbSQLITEPATH $1
shift
setenv rcdbSQLITEPATH $1
shift
setenv BGTAGONLY_OPTION $1
shift
setenv RADIATOR_THICKNESS $1
shift
setenv BGRATE $1
shift
setenv RANDBGTAG $1
shift
setenv RECON_CALIBTIME $1
shift
setenv GEANT_NOSECONDARIES $1
shift
setenv MCWRAPPER_VERSION $1
shift
setenv NOSIPMSATURATION $1
shift
setenv FLUX_TO_GEN $1
shift
setenv FLUX_HIST $1
shift
setenv POL_TO_GEN $1
shift
setenv POL_HIST $1
shift
setenv eBEAM_CURRENT $1
shift
setenv EXPERIMENT $1
shift
setenv RANDOM_TRIG_NUM_EVT $1
shift
setenv MCWRAPPER_RUN_LOCATION $1
shift
setenv GENERATOR_POST $1
shift
setenv GENERATOR_POST_CONFIG $1
shift
setenv GEANT_VERTEXT_AREA $1
shift
setenv GEANT_VERTEXT_LENGTH $1

setenv USER_BC `which bc`
setenv USER_PYTHON `which python`
setenv USER_STAT `which stat`

@ length_count=`echo $RUN_NUMBER | wc -c` - 1

set formatted_runNumber=""
while ( $length_count < 6 )
    set formatted_runNumber="0""$formatted_runNumber"
    @ length_count=$length_count + 1
end
set formatted_runNumber=$formatted_runNumber$RUN_NUMBER

if ( "$BATCHSYS" == "OSG" && "$BATCHRUN" == "1" ) then
setenv USER_BC '/usr/bin/bc'
setenv USER_STAT '/usr/bin/stat'
endif


setenv XRD_RANDOMS_URL root://sci-xrootd.jlab.org//osgpool/halld/

if ( "$MCWRAPPER_RUN_LOCATION" == "JLAB" ) then
	setenv XRD_RANDOMS_URL root://sci-xrootd-ib.qcd.jlab.org//osgpool/halld/
	setenv RUNNING_DIR "./"
endif

setenv MAKE_MC_USING_XROOTD 0
if ( -f /usr/lib64/libXrdPosixPreload.so && "$BKGFOLDSTR" != "None" ) then
	setenv MAKE_MC_USING_XROOTD 1
	setenv LD_PRELOAD /usr/lib64/libXrdPosixPreload.so
	echo "XROOTD is available for use if needed..."
	#set con_test=`ls $XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm`
	#echo `ls $XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm | head -c 1`
	if ( "$BKGFOLDSTR" == "Random" ) then
		if ( `ls $XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm | head -c 1` != "r" ) then
			echo "JLAB Connection test failed.  Falling back to UConn ...."
			#echo "attempting to copy the needed file from an alternate source..."
			setenv XRD_RANDOMS_URL root://nod25.phys.uconn.edu/Gluex/rawdata/
			if ( `ls $XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm | head -c 1` != "r" ) then
				echo "Cannot connect to the file.  Disabling xrootd...."
				setenv MAKE_MC_USING_XROOTD 0
			endif
		endif
	endif

endif

#necessary to run swif, uses local directory if swif=0 is used
if ( "$BATCHRUN" != "0"  ) then
# ENVIRONMENT
	echo $ENVIRONMENT
    echo pwd=$PWD
    mkdir -p $OUTDIR
    mkdir -p $OUTDIR/log
endif

if ( "$BATCHSYS" == "QSUB" ) then
	if ( ! -d $RUNNING_DIR ) then
		mkdir $RUNNING_DIR
	endif

cd $RUNNING_DIR

endif

if ( ! -d $RUNNING_DIR/${RUN_NUMBER}_${FILE_NUMBER} ) then
	mkdir $RUNNING_DIR/${RUN_NUMBER}_${FILE_NUMBER}
endif

cd $RUNNING_DIR/${RUN_NUMBER}_${FILE_NUMBER}
echo "what path?"
echo $ccdbSQLITEPATH
if ( "$ccdbSQLITEPATH" != "no_sqlite" && "$ccdbSQLITEPATH" != "batch_default" && "$ccdbSQLITEPATH" != "jlab_batch_default" ) then
	if (`$USER_STAT --file-system --format=%T $PWD` == "lustre" ) then
		echo "Attempting to use sqlite on a lustre file system. This does not work.  Try running on a different file system!"
		echo "something went wrong with initialization"
		exit 1
	endif
    cp $ccdbSQLITEPATH ./ccdb.sqlite
    setenv CCDB_CONNECTION sqlite:///$PWD/ccdb.sqlite
    setenv JANA_CALIB_URL ${CCDB_CONNECTION}
else if ( "$ccdbSQLITEPATH" == "batch_default" ) then
    setenv CCDB_CONNECTION sqlite:////group/halld/www/halldweb/html/dist/ccdb.sqlite
    setenv JANA_CALIB_URL ${CCDB_CONNECTION}
else if ( "$ccdbSQLITEPATH" == "jlab_batch_default" ) then
	#if ( -f /usr/lib64/libXrdPosixPreload.so ) then
	#	#echo "stop...its xrdcopy time"
	#	xrdcopy $XRD_RANDOMS_URL/ccdb.sqlite ./
	#	setenv CCDB_CONNECTION sqlite:///$PWD/ccdb.sqlite
	#else
	#	set ccdb_jlab_sqlite_path=`bash -c 'echo $((1 + RANDOM % 100))'`
	#	if ( -f /work/halld/ccdb_sqlite/$ccdb_jlab_sqlite_path/ccdb.sqlite ) then
	#		cp /work/halld/ccdb_sqlite/$ccdb_jlab_sqlite_path/ccdb.sqlite $PWD/ccdb.sqlite
	#		setenv CCDB_CONNECTION sqlite:///$PWD/ccdb.sqlite
	#		#setenv CCDB_CONNECTION sqlite:////work/halld/ccdb_sqlite/$ccdb_jlab_sqlite_path/ccdb.sqlite
	#	else
	#		setenv CCDB_CONNECTION mysql://ccdb_user@hallddb-farm.jlab.org/ccdb
	#	endif
	#endif
	setenv CCDB_CONNECTION mysql://ccdb_user@hallddb-farm.jlab.org/ccdb

	#setenv CCDB_CONNECTION mysql://ccdb_user@hallddb-farm.jlab.org/ccdb
    setenv JANA_CALIB_URL ${CCDB_CONNECTION}
endif


#setenv JANA_GEOMETRY_URL "ccdb:///GEOMETRY/main_HDDS.xml context=\"$VERSION\""
#xrdcopy $XRD_RANDOMS_URL/ccdb.sqlite ./
#setenv CCDB_CONNECTION sqlite:///$PWD/ccdb.sqlite
#setenv JANA_CALIB_URL ${CCDB_CONNECTION}

if ( "$rcdbSQLITEPATH" != "no_sqlite" && "$rcdbSQLITEPATH" != "batch_default" ) then
	if ( `$USER_STAT --file-system --format=%T $PWD` == "lustre" ) then
		echo "Attempting to use sqlite on a lustre file system. This does not work.  Try running on a different file system!"
		echo "something went wrong with initialization"
		exit 1
	endif
    cp $rcdbSQLITEPATH ./rcdb.sqlite
    setenv RCDB_CONNECTION sqlite:///$PWD/rcdb.sqlite
else if ( "$rcdbSQLITEPATH" == "batch_default" ) then
	#echo "keeping the RCDB on mysql now"
    setenv RCDB_CONNECTION sqlite:////group/halld/www/halldweb/html/dist/rcdb.sqlite 
endif

echo ""
echo ""
echo "Detected c-shell"

set current_files=`find . -maxdepth 1 -type f`

set beam_on_current="Not needed"
set radthick="Not needed"
set colsize="Not Needed"
set polarization_angle="Not Needed"
set BGRATE_toUse="Not Needed"


set gen_pre_rcdb=`echo $GENERATOR | cut -c1-4`
if ( $gen_pre_rcdb != "file" || ( "$BGTAGONLY_OPTION" == "1" || "$BKGFOLDSTR" == "BeamPhotons" ) ) then 
set radthick="50.e-6"

if ( "$RADIATOR_THICKNESS" != "rcdb" || ( "$VERSION" != "mc" && "$VERSION" != "mc_workfest2018" && "$VERSION" != "mc_cpp" ) ) then
    set radthick=$RADIATOR_THICKNESS
else
	set words = `rcnd $RUN_NUMBER radiator_type | sed 's/ / /g' `
	foreach word ($words:q)

		if ( $word != "number" ) then

			if ( "$word" == "3x10-4" ) then
				set radthick="30e-6"
				end
			else
				set removedum = `echo $word:q | sed 's/um/ /g'`

				if ( $removedum != $word:q ) then
					set radthick = `echo $removedum e-6 | tr -d '[:space:]'`
				endif
			endif
		endif
	end
endif
echo "Radiator thickness set..."
set polarization_angle=`rcnd $RUN_NUMBER polarization_angle | awk '{print $1}'`

if ( "$polarization_angle" == "" ) then
	set poldir=`rcnd $RUN_NUMBER polarization_direction | awk '{print $1}'`
	if ( "$poldir" == "PARA" ) then
		set polarization_angle="0.0"
	else if ( "$poldir" == "PERP" ) then
		set polarization_angle="90.0"
	else
		set polarization_angle="-1.0"
	endif
endif

echo "Polarization angle set..."
set elecE=0
set variation=$VERSION

if ( $CALIBTIME != "notime" ) then
set variation=$variation":"$CALIBTIME
endif


set ccdbelece="`ccdb dump PHOTON_BEAM/endpoint_energy:${RUN_NUMBER}:${variation} | grep -v \#`"

#set ccdblist=($ccdbelece:as/ / /)
echo $ccdbelece
set elecE_text="$ccdbelece" #$ccdblist[$#ccdblist]

#echo "text: " $elecE_text

if ( "$eBEAM_ENERGY" != "rcdb" || ( "$VERSION" != "mc" && "$VERSION" != "mc_workfest2018" && "$VERSION" != "mc_cpp" )  ) then
    set elecE=$eBEAM_ENERGY
else if ( $elecE_text == "Run" ) then
	set elecE=12
else if ( $elecE_text == "-1.0" ) then
	set elecE=12 #Should never happen
else
	set elecE=`echo $elecE_text`  #set elecE = `echo "$elecE_text / 1000" | $USER_BC -l ` #rcdb method
endif

echo "Electron beam energy set..."

set copeak = 0
set copeak_text = `rcnd $RUN_NUMBER coherent_peak | awk '{print $1}'`

if ( "$COHERENT_PEAK" != "rcdb" && "$polarization_angle" == "-1.0" ) then
	set copeak=$COHERENT_PEAK
else

	if ( "$COHERENT_PEAK" != "rcdb" || ( "$VERSION" != "mc" && "$VERSION" != "mc_workfest2018" && "$VERSION" != "mc_cpp" ) ) then
    	set copeak=$COHERENT_PEAK
	else if ( $copeak_text == "Run" ) then
		set copeak=9
	else if ( $copeak_text == "-1.0" ) then
		set copeak=0
	else
		set copeak = `echo "$copeak_text / 1000" | $USER_BC -l `
	endif
endif

if ( "$polarization_angle" == "-1.0" && "$COHERENT_PEAK" == "rcdb" ) then
	set copeak=0
endif

setenv COHERENT_PEAK $copeak
echo "Coherent peak set..."
#echo $copeak
#set copeak=`rcnd $RUN_NUMBER coherent_peak | awk '{print $1}' | sed 's/\.//g' #| awk -vFS="" -vOFS="" '{$1=$1"."}1' `

if ( ( "$VERSION" != "mc" && "$VERSION" != "mc_cpp" && "$VERSION" != "mc_workfest2018" ) && "$COHERENT_PEAK" == "rcdb" ) then
	echo "error in requesting rcdb for the coherent peak and not using variation=mc"
	echo "something went wrong with initialization"
	exit 1
endif

setenv eBEAM_ENERGY $elecE
echo "eBEAM energy set..."
if ( ( "$VERSION" != "mc" && "$VERSION" != "mc_cpp" && "$VERSION" != "mc_workfest2018" ) && "$eBEAM_ENERGY" == "rcdb" ) then
	echo "error in requesting rcdb for the electron beam energy and not using variation=mc"
	exit 1
endif

set colsize=`rcnd $RUN_NUMBER collimator_diameter | awk '{print $1}' | sed -r 's/.{2}$//' | sed -e 's/\.//g'`

if ( "$colsize" == "B" || "$colsize" == "R" || "$JANA_CALIB_CONTEXT" != "variation=mc" ) then
	set colsize="50"
endif
echo "Colimator size set..."

if ( "$eBEAM_CURRENT" == "rcdb" ) then
set beam_on_current=`rcnd $RUN_NUMBER beam_on_current | awk '{print $1}'`

if ( $beam_on_current == "" || $beam_on_current == "Run" ) then
	echo "Run $RUN_NUMBER does not have a beam_on_current.  Defaulting to beam_current."
	set beam_on_current=`rcnd $RUN_NUMBER beam_current | awk '{print $1}'`
endif

if ( $beam_on_current == "Run" ) then
	echo "The beam current could not be found for Run "$RUN_NUMBER".  This is most like due to the run number provided not existing in the rcdb"
	echo "Please set eBEAM_CURRENT explicitly in MC.config..."
	echo "something went wrong with initialization"
	exit 1
endif
set beam_on_current=`echo "$beam_on_current / 1000." | $USER_BC -l`
else
set beam_on_current=$eBEAM_CURRENT
endif

echo "beam (on) current set..."

set BGRATE_toUse=$BGRATE

if ( "$BGRATE" != "rcdb" || ( "$VERSION" != "mc" && "$VERSION" != "mc_workfest2018" && "$VERSION" != "mc_cpp" ) ) then
    set BGRATE_toUse=$BGRATE
else
	if ( $BGTAGONLY_OPTION == "1" || $BKGFOLDSTR == "BeamPhotons" ) then
		echo "Calculating BGRate.  This process takes a minute..."
		set BGRATE_toUse=`BGRate_calc --runNo $RUN_NUMBER --coherent_peak $COHERENT_PEAK --beam_on_current $beam_on_current --beam_energy $eBEAM_ENERGY --collimator_diameter 0.00$colsize --radiator_thickness $radthick --endpoint_energy_low $GEN_MIN_ENERGY --endpoint_energy_high $GEN_MAX_ENERGY`

		if ( "$BGRATE_toUse" == "" ) then
			echo "BGrate_calc is not built or inaccessible.  Please check your build and/or specify a BGRate to be used."
			exit 12
		else
			set BGRATE_list=($BGRATE_toUse:as/ / /)
			set BGRATE_toUse=$BGRATE_list[$#BGRATE_list]
		endif
	endif
endif

echo "BGrate set..."

if ( "$polarization_angle" == "-1.0" ) then
		set POL_TO_GEN=0
endif
endif
# PRINT INPUTS
echo "This job has been configured to run at: " $MCWRAPPER_RUN_LOCATION" : "`hostname`
echo "Job started: " `date`
echo "Simulating the Experiment: " $EXPERIMENT
echo "ccdb sqlite path: " $ccdbSQLITEPATH $CCDB_CONNECTION
echo "rcdb sqlite path: " $rcdbSQLITEPATH $RCDB_CONNECTION
echo "Producing file number: "$FILE_NUMBER
echo "Containing: " $EVT_TO_GEN"/""$PER_FILE"" events"
echo "Running location:" $RUNNING_DIR
echo "Output location: "$OUTDIR
echo "Environment file: " $ENVIRONMENT
echo "Analysis Environment file: " $ANAENVIRONMENT
echo "Context: "$JANA_CALIB_CONTEXT
echo "Geometry URL: "$JANA_GEOMETRY_URL
echo "Reconstruction calibtime: "$RECON_CALIBTIME
echo "Run Number: "$RUN_NUMBER
echo "Electron beam current to use: "$beam_on_current" uA"
echo "Electron beam energy to use: "$eBEAM_ENERGY" GeV"
echo "Radiator Thickness to use: "$radthick" m"
echo "Collimator Diameter: 0.00"$colsize" m"
echo "Photon Energy between "$GEN_MIN_ENERGY" and "$GEN_MAX_ENERGY" GeV"
echo "Polarization Angle: "$polarization_angle "degrees"
echo "Coherent Peak position: "$COHERENT_PEAK
echo "----------------------------------------------"
echo "Run generation step? "$GENR"  Will be cleaned?" $CLEANGENR
echo "Flux Hist to use: " "$FLUX_TO_GEN" " : " "$FLUX_HIST"
echo "Polarization to use: " "$POL_TO_GEN" " : " "$POL_HIST"
echo "Using "$GENERATOR"  with config: "$CONFIG_FILE
echo "Will run "$GENERATOR_POST" postprocessing after generator with configuration: "$GENERATOR_POST_CONFIG
echo "----------------------------------------------"
echo "Run geant step? "$GEANT"  Will be cleaned?" $CLEANGEANT
echo "Using geant"$GEANTVER
echo "Custom Gcontrol?" "$CUSTOM_GCONTROL"
echo "Background to use: "$BKGFOLDSTR
echo "Random trigger background to use: "$RANDBGTAG
echo "BGRATE will be set to: "$BGRATE_toUse" GHz (if applicable)"
echo "Run mcsmear? "$SMEAR"  Will be cleaned?" $CLEANSMEAR
echo "----------------------------------------------"
echo "Run reconstruction? "$RECON"  Will be cleaned?" $CLEANRECON
echo "With additional plugins: "$CUSTOM_PLUGINS
echo "=============================================="
echo ""
echo ""
echo "=======SOFTWARE USED======="
echo "MCwrapper version v"$MCWRAPPER_VERSION
echo "MCwrapper location" $MCWRAPPER_CENTRAL
echo "Streaming via xrootd? "$MAKE_MC_USING_XROOTD "Event Count: "$RANDOM_TRIG_NUM_EVT
echo "BC "$USER_BC
echo "python "$USER_PYTHON
echo `which $GENERATOR`
if ( "$GENERATOR_POST" != "No" ) then
echo `which $GENERATOR_POST`
endif
if ( "$GEANTVER" == "3" ) then
	echo `which hdgeant`
else
	echo `which hdgeant4`
endif
echo `which mcsmear`
echo `which hd_root`
echo ""
echo ""


set isGreater=1
set isGreater=`echo $GEN_MAX_ENERGY'>'$eBEAM_ENERGY | $USER_BC -l`

if ( "$isGreater" == "1" && "$eBEAM_ENERGY" != "rcdb" ) then
echo "something went wrong with initialization"
echo "Error: Requested Max photon energy $GEN_MAX_ENERGY is above the electron beam energy $eBEAM_ENERGY!"
exit 1
endif

if ( "$CUSTOM_GCONTROL" == "0" && "$GEANT" == "1" ) then
	#echo $MCWRAPPER_CENTRAL

	if ( "$EXPERIMENT" == "GlueX" ) then
		cp $MCWRAPPER_CENTRAL/Gcontrol.in ./temp_Gcontrol.in
	else if ( "$EXPERIMENT" == "CPP" ) then
		cp $MCWRAPPER_CENTRAL/Gcontrol_cpp.in ./temp_Gcontrol.in
	else
		cp $MCWRAPPER_CENTRAL/Gcontrol.in ./temp_Gcontrol.in
	endif

    chmod 777 ./temp_Gcontrol.in
else if ( "$CUSTOM_GCONTROL" != "0" && "$GEANT" == "1" ) then
    cp $CUSTOM_GCONTROL ./temp_Gcontrol.in
else
	echo "NO GEANT"
endif



@ flength_count=`echo $FILE_NUMBER | wc -c` - 1

set formatted_fileNumber=""
while ( $flength_count < 3 )
    set formatted_fileNumber="0""$formatted_fileNumber"
    @ flength_count=$flength_count + 1
end
set formatted_fileNumber=$formatted_fileNumber$FILE_NUMBER

set custom_tag=""

if ( "$TAGSTR" != "I_dont_have_one" ) then
    set custom_tag=$TAGSTR\_
endif

set STANDARD_NAME=$custom_tag$formatted_runNumber\_$formatted_fileNumber

if ( `echo $eBEAM_ENERGY | grep -o "\." | wc -l` == 0 ) then
    set eBEAM_ENERGY=$eBEAM_ENERGY\.
endif
if ( `echo $COHERENT_PEAK | grep -o "\." | wc -l` == 0 ) then
    set COHERENT_PEAK=$COHERENT_PEAK\.
endif
if ( `echo $GEN_MIN_ENERGY | grep -o "\." | wc -l` == 0 ) then
    set GEN_MIN_ENERGY=$GEN_MIN_ENERGY\.
endif
if ( `echo $GEN_MAX_ENERGY | grep -o "\." | wc -l` == 0 ) then
    set GEN_MAX_ENERGY=$GEN_MAX_ENERGY\.
endif

#echo `-d "$OUTDIR"`
if ( ! -d "$OUTDIR" ) then
    echo "making dir"
    mkdir -p $OUTDIR
endif
if ( ! -d "$OUTDIR/configurations/" ) then
    mkdir -p $OUTDIR/configurations/
endif
if ( ! -d "$OUTDIR/configurations/generation/" ) then
    mkdir -p $OUTDIR/configurations/generation/
endif
if ( ! -d "$OUTDIR/configurations/geant/" ) then
    mkdir -p $OUTDIR/configurations/geant/
endif
if ( ! -d "$OUTDIR/hddm/" ) then
    mkdir -p $OUTDIR/hddm/
endif
if ( ! -d "$OUTDIR/root/" ) then
    mkdir -p $OUTDIR/root/
endif

set bkglocstring=""
set bkgloc_pre=`echo $BKGFOLDSTR | cut -c 1-4`

if ( "$BKGFOLDSTR" == "DEFAULT" || "$bkgloc_pre" == "loc:" || "$BKGFOLDSTR" == "Random" ) then
    #find file and run:1
	if ( "$RANDBGTAG" == "none" && "$bkgloc_pre" != "loc:" ) then
		echo "Random background requested but no tag given. Please provide the desired tag e.g Random:recon-2017_01-ver03"
		echo "something went wrong with initialization"
		exit 1
	endif

    echo "Finding the right file to fold in during MCsmear step"
    set runperiod="RunPeriod-2018-01"

    if ( $RUN_NUMBER >= 40000 ) then
		set runperiod="RunPeriod-2018-01"
	else if ( $RUN_NUMBER >= 30000 ) then
		set runperiod="RunPeriod-2017-01"
	else if ( $RUN_NUMBER >= 20000 ) then
		set runperiod="RunPeriod-2016-10"
	else if ( $RUN_NUMBER >= 10000 ) then
		set runperiod="RunPeriod-2016-02"
    endif

    if ( $RUN_NUMBER < 10000 ) then
		echo "Warning: random triggers do not exist for this run"
		echo "something went wrong with initialization"
		exit 1
    endif
	
	if ( "$bkgloc_pre" == "loc:" ) then
		set rand_bkg_loc=`echo $BKGFOLDSTR | cut -c 5-`
		 if ( "$BATCHSYS" == "OSG" && $BATCHRUN != 0 ) then
        if ( "$MAKE_MC_USING_XROOTD" == "0" ) then
					set	bkglocstring="/srv""/run$formatted_runNumber""_random.hddm"
				else
					set	bkglocstring="$XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm"
				endif
		 else
		    set bkglocstring=$rand_bkg_loc"/run$formatted_runNumber""_random.hddm"
		 endif
	else
		#set bkglocstring="/cache/halld/""$runperiod""/sim/random_triggers/""run$formatted_runNumber""_random.hddm"
		if ( "$BATCHSYS" == "OSG" && $BATCHRUN != 0 ) then
			if ( "$MAKE_MC_USING_XROOTD" == "0" ) then
				set	bkglocstring="/srv""/run$formatted_runNumber""_random.hddm"
			else
				set	bkglocstring="$XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm"
			endif
    else
			set bkglocstring="/work/osgpool/halld/random_triggers/"$RANDBGTAG"/run"$formatted_runNumber"_random.hddm"
			if ( `hostname` == 'scosg16.jlab.org' ) then
				set bkglocstring="/work/osgpool/halld/random_triggers/"$RANDBGTAG"/run"$formatted_runNumber"_random.hddm"
			endif
		endif
	endif
	
  if ( ! -f $bkglocstring && "$MAKE_MC_USING_XROOTD" == "0" ) then
		echo "something went wrong with initialization"
		echo "Could not find mix-in file "$bkglocstring
		exit 1000
  endif
endif

set recon_pre=`echo $CUSTOM_PLUGINS | cut -c1-4`
set jana_config_file=`echo $CUSTOM_PLUGINS | sed -r 's/^.{5}//'`

if ( $recon_pre == "file" ) then
	if ( -f $jana_config_file ) then
    	cp $jana_config_file ./jana_config.cfg
	endif
endif

set gen_pre=""

if ( "$GENR" != "0" ) then

    set gen_pre=`echo $GENERATOR | cut -c1-4`

    if ( "$gen_pre" != "file" && "$GENERATOR" != "genr8" && "$GENERATOR" != "bggen" && "$GENERATOR" != "genEtaRegge" && "$GENERATOR" != "gen_2pi_amp" && "$GENERATOR" != "gen_pi0" && "$GENERATOR" != "gen_2pi_primakoff" && "$GENERATOR" != "gen_2pi0_primakoff" && "$GENERATOR" != "gen_omega_3pi" && "$GENERATOR" != "gen_omegapi" && "$GENERATOR" != "gen_2k" && "$GENERATOR" != "bggen_jpsi" && "$GENERATOR" != "gen_ee" && "$GENERATOR" != "gen_ee_hb" && "$GENERATOR" != "particle_gun" && "$GENERATOR" != "bggen_phi_ee" && "$GENERATOR" != "genBH" && "$GENERATOR" != "gen_omega_radiative" && "$GENERATOR" != "gen_amp" && "$GENERATOR" != "genr8_new" && "$GENERATOR" != "gen_compton" && "$GENERATOR" != "gen_npi" && "$GENERATOR" != "gen_compton_simple" && "$GENERATOR" != "gen_primex_eta_he4" && "$GENERATOR" != "gen_whizard" && "$GENERATOR" != "mc_gen") then
		echo "NO VALID GENERATOR GIVEN"
		echo "only [genr8, bggen, genEtaRegge, gen_2pi_amp, gen_pi0, gen_omega_3pi, gen_2k, bggen_jpsi, gen_ee , gen_ee_hb, bggen_phi_ee, particle_gun, genBH, gen_omega_radiative, gen_amp, gen_compton, gen_npi, gen_compton_simple, gen_primex_eta_he4, gen_whizard, gen_omegapi, mc_gen] are supported"
		echo "something went wrong with initialization"
		exit 1
    endif

    if ( "$gen_pre" == "file" ) then
		set gen_in_file=`echo $GENERATOR | sed -r 's/^.{5}//'`
		echo "bypassing generation"
		echo "using "$gen_in_file

		set generator_return_code=0
		if ( -f $gen_in_file ) then
	    	echo "using pre-generated file: "$gen_in_file
	    	cp $gen_in_file ./$STANDARD_NAME.hddm
		else
	    	echo "cannot find file: "$gen_in_file
			echo "something went wrong with initialization"
	    	exit 1
		endif
	else if ( "$GENERATOR" == "particle_gun" ) then
		echo "bypassing generation" 
		if ( "$CUSTOM_GCONTROL" == "0" ) then
			if ( ! -f $CONFIG_FILE ) then
				echo "Generator config file : "$CONFIG_FILE" not found"
				echo "something went wrong with initialization"
				exit 1
			else
				echo `grep KINE $CONFIG_FILE | awk '{print $2}' `
				if ( `grep "^[^c]" | grep KINE $CONFIG_FILE | awk '{print $2}' ` < 100 && `grep "^[^c]" | grep KINE $CONFIG_FILE | wc -w` > 3 ) then
					echo "ERROR THETA AND PHI APPEAR TO BE SET BUT WILL BE IGNORED.  PLEASE REMOVE THESE SETTINGS FROM:"$CONFIG_FILE" AND RESUBMIT."
					echo "something went wrong with initialization"
					exit 1
				else if ( `grep "^[^c]" | grep KINE $CONFIG_FILE | awk '{print $2}' ` > 100 && ` grep "^[^c]" | grep KINE $CONFIG_FILE | wc -w` < 8 ) then
					echo "ERROR THETA AND PHI DON'T APPEAR TO BE SET BUT ARE GOING TO BE USED. PLEASE ADD THESE SETTINGS FROM: "$CONFIG_FILE" AND RESUBMIT."
					echo "something went wrong with initialization"
					exit 1
				endif
			endif
		endif
		set generator_return_code=0
	else 
		if ( -f $CONFIG_FILE ) then
		    echo "input file found"
		else if( "$GENERATOR" == "gen_ee" || "$GENERATOR" == "gen_ee_hb" || "$GENERATOR" == "genBH" ) then
			echo "Config file not applicable"
		else
	    	echo $CONFIG_FILE" does not exist"
			echo "something went wrong with initialization"
	    	exit 1
    	endif
	endif
	echo $GENERATOR


	echo "PolarizationAngle $polarization_angle" > beam.config
	echo "PhotonBeamLowEnergy $GEN_MIN_ENERGY" >>! beam.config
	echo "PhotonBeamHighEnergy $GEN_MAX_ENERGY" >>! beam.config

	if ( "$FLUX_TO_GEN" == "ccdb" ) then
		echo "CCDBRunNumber $RUN_NUMBER" >>! beam.config
		echo "ROOTFluxFile $FLUX_TO_GEN" >>! beam.config
		if ( "$POL_TO_GEN" == "ccdb" ) then
			echo "ROOTPolFile $POL_TO_GEN" >>! beam.config
		else if ( "$POL_HIST" == "unset" ) then
			echo "PolarizationMagnitude $POL_TO_GEN" >>! beam.config
		else
			echo "ROOTPolFile $POL_TO_GEN" >>! beam.config
			echo "ROOTPolName $POL_HIST" >>! beam.config
		endif
	else if ( "$FLUX_TO_GEN" == "cobrems" ) then
		echo "ElectronBeamEnergy $eBEAM_ENERGY" >>! beam.config
		echo "CoherentPeakEnergy $COHERENT_PEAK" >>! beam.config
		echo "Emittance  2.5.e-9" >>! beam.config
		echo "RadiatorThickness $radthick" >>! beam.config
		echo "CollimatorDiameter 0.00$colsize" >>! beam.config
		echo "CollimatorDistance  76.0" >>! beam.config

		if ( "$POL_TO_GEN" == "ccdb" ) then
			echo "Ignoring TPOL from ccdb in favor of cobrems generated values"
		else if ( "$POL_HIST" == "cobrems" ) then
			echo "PolarizationMagnitude $POL_TO_GEN" >>! beam.config
		else if ( "$POL_HIST" != "unset" ) then
			echo "Ignoring TPOL from $POL_TO_GEN in favor of cobrems generated values"
		endif

	else
		echo "ROOTFluxFile $FLUX_TO_GEN" >>! beam.config
		echo "ROOTFluxName $FLUX_HIST" >>! beam.config
		if ( "$POL_TO_GEN" == "ccdb" ) then
			echo "Can't use a flux file and Polarization from ccdb"
			echo "something went wrong with initialization"
			exit 1
		else if ( "$POL_HIST" == "unset" ) then
			echo "PolarizationMagnitude $POL_TO_GEN" >>! beam.config
		else
			echo "ROOTPolFile $POL_TO_GEN" >>! beam.config
			echo "ROOTPolName $POL_HIST" >>! beam.config
		endif
	endif

    

    if ( "$GENERATOR" == "genr8" ) then
		echo "configuring genr8"
		set STANDARD_NAME="genr8_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
		set replacementNum=`grep TEMPCOHERENT ./$STANDARD_NAME.conf | wc -l`

		#if ( "$polarization_angle" == "-1.0" && "$COHERENT_PEAK" == "0." && $replacementNum != 0 && "1"=="0" ) then
		#	echo "Running genr8 with an AMO run number without supplying the energy desired to COHERENT_PEAK causes an inifinite loop."
		#	echo "Please specify the desired energy via the COHERENT_PEAK parameter and retry."
		#	exit 1
		#endif
	else if ( "$GENERATOR" == "genr8_new" ) then
		echo "configuring new genr8"

		set STANDARD_NAME="genr8_new_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
		
    else if ( "$GENERATOR" == "bggen" ) then
		echo "configuring bggen"
		set STANDARD_NAME="bggen_"$STANDARD_NAME
		cp $MCWRAPPER_CENTRAL/Generators/bggen/particle.dat ./
		cp $MCWRAPPER_CENTRAL/Generators/bggen/pythia.dat ./
		cp $MCWRAPPER_CENTRAL/Generators/bggen/pythia-geant.map ./
		cp $CONFIG_FILE ./$STANDARD_NAME.conf	
    else if ( "$GENERATOR" == "genEtaRegge" ) then
		echo "configuring genEtaRegge"
		set STANDARD_NAME="genEtaRegge_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_amp" ) then
		echo "configuring gen_amp"
		set STANDARD_NAME="gen_amp_"$STANDARD_NAME	
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
    else if ( "$GENERATOR" == "gen_2pi_amp" ) then
		echo "configuring gen_2pi_amp"
		set STANDARD_NAME="gen_2pi_amp_"$STANDARD_NAME	
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_omega_3pi" ) then
		echo "configuring gen_omega_3pi"
		set STANDARD_NAME="gen_omega_3pi_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_omegapi" ) then
		echo "configuring gen_omegapi"
		set STANDARD_NAME="gen_omegapi_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_omega_radiative" ) then
		echo "configuring gen_omega_radiative"
		set STANDARD_NAME="gen_omega_radiative_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_2pi_primakoff" ) then
		echo "configuring gen_2pi_primakoff"
		set STANDARD_NAME="gen_2pi_primakoff_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "mc_gen" ) then
		echo "configuring mc_gen"
		set STANDARD_NAME="mc_gen_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_2pi0_primakoff" ) then
        echo "configuring gen_2pi0_primakoff"
        set STANDARD_NAME="gen_2pi0_primakoff_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_pi0" ) then
		echo "configuring gen_pi0"
		set STANDARD_NAME="gen_pi0_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_compton" ) then
		echo "configuring gen_compton"
		set STANDARD_NAME="gen_compton_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
        else if ( "$GENERATOR" == "gen_compton_simple" ) then
		echo "configuring gen_compton_simple"
		STANDARD_NAME="gen_compton_simple_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
        else if ( "$GENERATOR" == "gen_primex_eta_he4" ) then
		echo "configuring gen_primex_eta_he4"
		STANDARD_NAME="gen_primex_eta_he4_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
        else if ( "$GENERATOR" == "gen_whizard" ) then
		echo "configuring gen_whizard"
		STANDARD_NAME="gen_whizard_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_npi" ) then
		echo "configuring gen_npi"
		set STANDARD_NAME="gen_pipn_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_2k" ) then
		echo "configuring gen_2k"
		set STANDARD_NAME="gen_2k_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "bggen_jpsi" ) then
		echo "configuring bggen_jpsi"
		set STANDARD_NAME="bggen_jpsi_"$STANDARD_NAME
		cp $MCWRAPPER_CENTRAL/Generators/bggen_jpsi/particle.dat ./
		cp $MCWRAPPER_CENTRAL/Generators/bggen_jpsi/pythia.dat ./
		cp $MCWRAPPER_CENTRAL/Generators/bggen_jpsi/pythia-geant.map ./
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "bggen_phi_ee" ) then
		echo "configuring bggen_phi_ee"
		set STANDARD_NAME="bggen_phi_ee_"$STANDARD_NAME
		cp $MCWRAPPER_CENTRAL/Generators/bggen_phi_ee/particle.dat ./
		cp $MCWRAPPER_CENTRAL/Generators/bggen_phi_ee/pythia.dat ./
		cp $MCWRAPPER_CENTRAL/Generators/bggen_phi_ee/pythia-geant.map ./
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "gen_ee" ) then
		echo "configuring gen_ee"
		set STANDARD_NAME="gen_ee_"$STANDARD_NAME
		echo "note: this generator is run completely from command line, thus no config file will be made and/or modified"
		cp $CONFIG_FILE ./cobrems.root
	else if ( "$GENERATOR" == "gen_ee_hb" ) then
		echo "configuring gen_ee_hb"
		set STANDARD_NAME="gen_ee_hb_"$STANDARD_NAME
		echo "note: this generator is run completely from command line, thus no config file will be made and/or modified"
		cp $CONFIG_FILE ./cobrems.root
		cp $MCWRAPPER_CENTRAL/Generators/gen_ee_hb/CFFs_DD_Feb2012.dat ./
	else if ( "$GENERATOR" == "particle_gun" ) then
		echo "configuring the particle gun"
		set STANDARD_NAME="particle_gun_"$STANDARD_NAME
		cp $CONFIG_FILE ./$STANDARD_NAME.conf
	else if ( "$GENERATOR" == "genBH" ) then
		echo "configuring genBH"
		set STANDARD_NAME="genBH_"$STANDARD_NAME
		echo "note: this generator is run completely from command line, thus no config file will be made and/or modified"
		cp $CONFIG_FILE ./cobrems.root

    endif

    if ( "$gen_pre" != "file" ) then
		set config_file_name=`basename "$CONFIG_FILE"`
		echo config file name: $config_file_name
    endif
    
	cp beam.config $STANDARD_NAME\_beam.conf

    if ( "$GENERATOR" == "genr8" ) then
		echo "RUNNING GENR8"
		set RUNNUM=$formatted_runNumber+$formatted_fileNumber
		#sed -i 's/TEMPCOHERENT/'$COHERENT_PEAK'/' $STANDARD_NAME.conf
		#sed -i 's/TEMPMAXE/'$GEN_MAX_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		# RUN genr8 and convert
		genr8 -r$formatted_runNumber -M$EVT_TO_GEN -A$STANDARD_NAME.ascii < $STANDARD_NAME.conf
		set generator_return_code=$status
		genr8_2_hddm -V"0 0 0 0" $STANDARD_NAME.ascii
	else if ( "$GENERATOR" == "genr8_new" ) then
		echo "RUNNING NEW GENR8"
		set RUNNUM=$formatted_runNumber+$formatted_fileNumber
		#sed -i 's/TEMPCOHERENT/'$COHERENT_PEAK'/' $STANDARD_NAME.conf
		# RUN genr8 and convert
		genr8_new -r$formatted_runNumber -M$EVT_TO_GEN -C$GEN_MIN_ENERGY,$GEN_MAX_ENERGY -o$STANDARD_NAME.gamp < $STANDARD_NAME.conf #$config_file_name
		set generator_return_code=$status
		gamp_2_hddm -r$formatted_runNumber -V"0 0 0 0" $STANDARD_NAME.gamp
    else if ( "$GENERATOR" == "bggen" ) then
		set RANDOMnum=`bash -c 'echo $RANDOM'`
		
		echo Random Number used: $RANDOMnum
		sed -i 's/TEMPTRIG/'$EVT_TO_GEN'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRUNNO/'$RUN_NUMBER'/' $STANDARD_NAME.conf
		sed -i 's/TEMPCOLD/'0.00$colsize'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRAND/'$RANDOMnum'/' $STANDARD_NAME.conf
		set Fortran_eBEAM_ENRGY=`echo $eBEAM_ENERGY | cut -c -7`
		sed -i 's/TEMPELECE/'$Fortran_eBEAM_ENRGY'/' $STANDARD_NAME.conf
		set Fortran_COHERENT_PEAK=`echo $COHERENT_PEAK | cut -c -7`
		sed -i 's/TEMPCOHERENT/'$Fortran_COHERENT_PEAK'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMINGENE/'$GEN_MIN_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMAXGENE/'$GEN_MAX_ENERGY'/' $STANDARD_NAME.conf
	
		ln -s $STANDARD_NAME.conf fort.15
		bggen
		set generator_return_code=$status
		mv bggen.hddm $STANDARD_NAME.hddm
    else if ( "$GENERATOR" == "genEtaRegge" ) then
		echo "RUNNING GENETAREGGE" 
		sed -i 's/TEMPCOLD/'0.00$colsize'/' $STANDARD_NAME.conf
		sed -i 's/TEMPELECE/'$eBEAM_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPCOHERENT/'$COHERENT_PEAK'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRADTHICK/'"$radthick"'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMINGENE/'$GEN_MIN_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMAXGENE/'$GEN_MAX_ENERGY'/' $STANDARD_NAME.conf

		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		genEtaRegge -N$EVT_TO_GEN -O$STANDARD_NAME.hddm -I$STANDARD_NAME.conf
	    set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_amp" ) then
		echo "RUNNING GEN_AMP" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`

		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		if ( "$polarization_angle" == "-1.0" ) then
			sed -i 's/TEMPPOLFRAC/'0'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'0'/' $STANDARD_NAME.conf
		else
			sed -i 's/TEMPPOLFRAC/'.4'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'$polarization_angle'/' $STANDARD_NAME.conf
		endif
		
		echo $optionals_line
		echo gen_amp -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY  $optionals_line
		gen_amp -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "mc_gen" ) then
		echo "RUNNING MC_GEN" 
		python $HD_UTILITIES_HOME/psflux/plot_flux_ccdb.py -b $RUN_NUMBER -e $RUN_NUMBER
		set MCGEN_FLUX_DIR=`printf './flux_%d_%d.ascii' "$RUN_NUMBER" "$RUN_NUMBER"`
		set ROOTSCRIPT=`printf '$MCWRAPPER_CENTRAL/Generators/mc_gen/Flux_to_Ascii.C("flux_%s_%s.root")' "$RUN_NUMBER" "$RUN_NUMBER" `
		root -l -b -q $ROOTSCRIPT

		echo $MCGEN_FLUX_DIR

		sed -i 's/TEMPTRIG/'$EVT_TO_GEN'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMINGENE/'$GEN_MIN_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMAXGENE/'$GEN_MAX_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's|TEMPFLUXDIR|'$MCGEN_FLUX_DIR'|' $STANDARD_NAME.conf
		sed -i 's|TEMPOUTNAME|'./'|' $STANDARD_NAME.conf
		set MCGEN_Translator=`grep Translator $STANDARD_NAME.conf`
		
		echo mc_gen $STANDARD_NAME.conf
		mc_gen $STANDARD_NAME.conf

		rm flux_*
		mv *.ascii $STANDARD_NAME.ascii
		echo $MCGEN_Translator
		if ( "$MCGEN_Translator" == "\!Translator:ppbar" ) then
		echo GEN2HDDM_ppbar $STANDARD_NAME.ascii
		GEN2HDDM_ppbar $STANDARD_NAME.ascii
		else if ( "$MCGEN_Translator" == "\!Translator:lamlambar" ) then
		GEN2HDDM_lamlambar $STANDARD_NAME.ascii
		endif

    	set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_2pi_amp" ) then
		echo "RUNNING GEN_2PI_AMP" 
    	set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`

		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		if ( "$polarization_angle" == "-1.0" ) then
			sed -i 's/TEMPPOLFRAC/'0'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'0'/' $STANDARD_NAME.conf
		else
			sed -i 's/TEMPPOLFRAC/'.4'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'$polarization_angle'/' $STANDARD_NAME.conf
		endif
		
		echo $optionals_line
		echo gen_2pi_amp -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_2pi_amp -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_omega_3pi" ) then
		echo "RUNNING GEN_OMEGA_3PI" 
    	set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`

		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		if ( "$polarization_angle" == "-1.0" ) then
			sed -i 's/TEMPPOLFRAC/'0'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'0'/' $STANDARD_NAME.conf
		else
			sed -i 's/TEMPPOLFRAC/'.4'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'$polarization_angle'/' $STANDARD_NAME.conf
		endif
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		echo $optionals_line
		echo gen_omega_3pi -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_omega_3pi -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_omegapi" ) then
		echo "RUNNING GEN_OMEGAPI" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`

		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		if ( "$polarization_angle" == "-1.0" ) then
			sed -i 's/TEMPPOLFRAC/'0'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'0'/' $STANDARD_NAME.conf
		else
			sed -i 's/TEMPPOLFRAC/'.4'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'$polarization_angle'/' $STANDARD_NAME.conf
		endif
		
		echo $optionals_line
		echo gen_omegapi -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY  $optionals_line
		gen_omegapi -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_omega_radiative" ) then
		echo "RUNNING GEN_OMEGA_radiative" 
    	set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`

		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		if ( "$polarization_angle" == "-1.0" ) then
			sed -i 's/TEMPPOLFRAC/'0'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'0'/' $STANDARD_NAME.conf
		else
			sed -i 's/TEMPPOLFRAC/'.4'/' $STANDARD_NAME.conf
			sed -i 's/TEMPPOLANGLE/'$polarization_angle'/' $STANDARD_NAME.conf
		endif

		echo $optionals_line
		echo gen_omega_radiative -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_omega_radiative -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_2pi_primakoff" ) then
		echo "RUNNING GEN_2PI_PRIMAKOFF" 
        set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		echo gen_2pi_primakoff -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_2pi_primakoff -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_2pi0_primakoff" ) then
        echo "RUNNING GEN_2PI0_PRIMAKOFF"
        set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
        echo gen_2pi0_primakoff -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
        gen_2pi0_primakoff -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_pi0" ) then
		echo "RUNNING GEN_PI0" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		echo gen_pi0 -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_pi0 -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_compton" ) then
		echo "RUNNING GEN_COMPTON" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		echo gen_compton -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_compton -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status

        else if ( "$GENERATOR" == "gen_compton_simple" ) then
		echo "RUNNING GEN_COMPTON_SIMPLE" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		gen_compton_simple -c $STANDARD_NAME'_beam.conf' -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK  -s $formatted_fileNumber -m $eBEAM_ENERGY $optionals_line
		
		set generator_return_code=$status

        else if ( "$GENERATOR" == "gen_primex_eta_he4" ) then
		echo "RUNNING GEN_PRIMEX_ETA_HE4" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		gen_primex_eta_he4 -e $STANDARD_NAME.conf -c $STANDARD_NAME'_beam.conf' -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.txt -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -s $formatted_fileNumber -m $eBEAM_ENERGY $optionals_line

		set generator_return_code=$status

        else if ( "$GENERATOR" == "gen_whizard" ) then
		echo "RUNNING GEN_WHIZARD" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		gen_whizard -e $STANDARD_NAME.conf -c $STANDARD_NAME'_beam.conf' -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.txt -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -s $formatted_fileNumber -m $eBEAM_ENERGY $optionals_line
		
		set generator_return_code=$status

	else if ( "$GENERATOR" == "gen_npi" ) then
		echo "RUNNING GEN_NPI" 
		set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		echo gen_npi -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_npi -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "gen_2k" ) then
		echo "RUNNING GEN_2K" 
    	set optionals_line=`head -n 1 $STANDARD_NAME.conf | sed -r 's/.//'`
		#set RANDOMnum=`bash -c 'echo $RANDOM'`
		echo $optionals_line
		sed -i 's/TEMPBEAMCONFIG/'$STANDARD_NAME'_beam.conf/' $STANDARD_NAME.conf
		echo gen_2k -c $STANDARD_NAME.conf -o $STANDARD_NAME.hddm -hd $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		gen_2k -c $STANDARD_NAME.conf -hd $STANDARD_NAME.hddm -o $STANDARD_NAME.root -n $EVT_TO_GEN -r $RUN_NUMBER -a $GEN_MIN_ENERGY -b $GEN_MAX_ENERGY -p $COHERENT_PEAK -m $eBEAM_ENERGY $optionals_line
		set generator_return_code=$status
	else if ( "$GENERATOR" == "bggen_jpsi" ) then
		set RANDOMnum=`bash -c 'echo $RANDOM'`
		echo Random Number used: $RANDOMnum
		sed -i 's/TEMPTRIG/'$EVT_TO_GEN'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRUNNO/'$RUN_NUMBER'/' $STANDARD_NAME.conf
		sed -i 's/TEMPCOLD/'0.00$colsize'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRAND/'$RANDOMnum'/' $STANDARD_NAME.conf
		set Fortran_eBEAM_ENRGY=`echo $eBEAM_ENERGY | cut -c -7`
		sed -i 's/TEMPELECE/'$Fortran_eBEAM_ENRGY'/' $STANDARD_NAME.conf
		set Fortran_COHERENT_PEAK=`echo $COHERENT_PEAK | cut -c -7`
		sed -i 's/TEMPCOHERENT/'$Fortran_COHERENT_PEAK'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMINGENE/'$GEN_MIN_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMAXGENE/'$GEN_MAX_ENERGY'/' $STANDARD_NAME.conf
	
		ln -s $STANDARD_NAME.conf fort.15
		bggen_jpsi
		set generator_return_code=$status
		mv bggen.hddm $STANDARD_NAME.hddm
	else if ( "$GENERATOR" == "bggen_phi_ee" ) then
		set RANDOMnum=`bash -c 'echo $RANDOM'`
		echo Random Number used: $RANDOMnum
		sed -i 's/TEMPTRIG/'$EVT_TO_GEN'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRUNNO/'$RUN_NUMBER'/' $STANDARD_NAME.conf
		sed -i 's/TEMPCOLD/'0.00$colsize'/' $STANDARD_NAME.conf
		sed -i 's/TEMPRAND/'$RANDOMnum'/' $STANDARD_NAME.conf
		set Fortran_eBEAM_ENRGY=`echo $eBEAM_ENERGY | cut -c -7`
		sed -i 's/TEMPELECE/'$Fortran_eBEAM_ENRGY'/' $STANDARD_NAME.conf
		set Fortran_COHERENT_PEAK=`echo $COHERENT_PEAK | cut -c -7`
		sed -i 's/TEMPCOHERENT/'$Fortran_COHERENT_PEAK'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMINGENE/'$GEN_MIN_ENERGY'/' $STANDARD_NAME.conf
		sed -i 's/TEMPMAXGENE/'$GEN_MAX_ENERGY'/' $STANDARD_NAME.conf
	
		ln -s $STANDARD_NAME.conf fort.15
		bggen_jpsi
		set generator_return_code=$status
		mv bggen.hddm $STANDARD_NAME.hddm
	else if ( "$GENERATOR" == "gen_ee" ) then
		set RANDOMnum=`bash -c 'echo $RANDOM'`
		echo "Random number used: "$RANDOMnum
		echo gen_ee -n$EVT_TO_GEN -R2 -b2 -l$GEN_MIN_ENERGY -u$GEN_MAX_ENERGY -t2 -r$RANDOMnum -omc_ee.hddm
		gen_ee -n$EVT_TO_GEN -R2 -b2 -l$GEN_MIN_ENERGY -u$GEN_MAX_ENERGY -t2 -r$RANDOMnum -omc_ee.hddm
		set generator_return_code=$status
		mv mc_ee.hddm $STANDARD_NAME.hddm
	else if ( "$GENERATOR" == "gen_ee_hb" ) then
		echo gen_ee_hb -N$RUN_NUMBER -n$EVT_TO_GEN
		gen_ee_hb -N$RUN_NUMBER -n$EVT_TO_GEN
		set generator_return_code=$status
		mv genOut.hddm $STANDARD_NAME.hddm
	else if ( "$GENERATOR" == "genBH" ) then
		set RANDOMnum=`bash -c 'echo $RANDOM'`
		echo Random Number used: $RANDOMnum
		echo genBH -n$EVT_TO_GEN -t$NUMTHREADS -m0.5 -e$GEN_MAX_ENERGY -r$RANDOMnum $STANDARD_NAME.hddm
		genBH -n$EVT_TO_GEN -t$NUMTHREADS -m0.5 -e$GEN_MAX_ENERGY -r$RANDOMnum $STANDARD_NAME.hddm
		sed -i 's/class="mc_s"/'class=\"s\"'/' $STANDARD_NAME.hddm
		set generator_return_code=$status
	endif



    if ( ! -f ./$STANDARD_NAME.hddm && "$GENERATOR" != "particle_gun" && "$gen_pre" != "file" ) then
		echo "something went wrong with generation"
		echo "An hddm file was not found after generation step.  Terminating MC production.  Please consult logs to diagnose"
		exit 11
	endif

	if ( $generator_return_code != 0 ) then
				echo
				echo
				echo "Something went wrong with " "$GENERATOR"
				echo "status code: "$generator_return_code
				exit $generator_return_code
	endif
#GEANT/smearing
endif

if ( "$GENERATOR_POST" != "No" ) then
	echo "RUNNING POSTPROCESSING "
#copy config locally
	set post_return_code=-1
	echo $GENERATOR_POST_CONFIG
	if ( "$GENERATOR_POST_CONFIG" != "Default" ) then
		cp $GENERATOR_POST_CONFIG ./post'_'$GENERATOR_POST'_'$formatted_runNumber'_'$formatted_fileNumber.cfg
	endif

	if ( "$GENERATOR_POST" == "decay_evtgen" ) then
		echo decay_evtgen -o$STANDARD_NAME'_decay_evtgen'.hddm $STANDARD_NAME.hddm
		decay_evtgen -o$STANDARD_NAME'_decay_evtgen'.hddm -upost'_'$GENERATOR_POST'_'$formatted_runNumber'_'$formatted_fileNumber.cfg $STANDARD_NAME.hddm
		set post_return_code=$status
		set STANDARD_NAME=$STANDARD_NAME'_decay_evtgen'
	endif
	#do if/elses for running 
	if ( $post_return_code != 0 ) then
				echo
				echo
				echo "Something went wrong with " "$GENERATOR_POST"
				echo "status code: "$post_return_code
				exit $post_return_code
	endif
endif

    if ( "$GEANT" != "0"  ) then
		echo "RUNNING GEANT"$GEANTVER

		if ( `echo $eBEAM_ENERGY | grep -o "\." | wc -l` == 0 ) then
	   		set eBEAM_ENERGY=$eBEAM_ENERGY\.
		endif
	
		if ( `echo $COHERENT_PEAK | grep -o "\." | wc -l` == 0 ) then
	    	set COHERENT_PEAK=$COHERENT_PEAK\.
		endif

		cp temp_Gcontrol.in $PWD/control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		chmod 777 $PWD/control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		#a 4byte int: od -vAn -N4 -tu4 < /dev/urandom
		set RANDOMnumGeant=`shuf -i1-215 -n1`
		sed -i 's/TEMPRANDOM/'$RANDOMnumGeant'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		sed -i 's/TEMPELECE/'$eBEAM_ENERGY'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		
		if ( "$polarization_angle" == "-1" ) then
			sed -i 's/TEMPCOHERENT/'0'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		else
			set Fortran_COHERENT_PEAK=`echo $COHERENT_PEAK | cut -c -7`
			sed -i 's/TEMPCOHERENT/'$Fortran_COHERENT_PEAK'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		endif
		
		sed -i 's/TEMPIN/'$STANDARD_NAME.hddm'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		sed -i 's/TEMPRUNG/'$RUN_NUMBER'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		sed -i 's/TEMPOUT/'$STANDARD_NAME'_geant'$GEANTVER'.hddm/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		sed -i 's/TEMPTRIG/'$EVT_TO_GEN'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in

		sed -i 's/TEMPGEANTAREA/'$GEANT_VERTEXT_AREA'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		sed -i 's/TEMPGEANTLENGTH/'$GEANT_VERTEXT_LENGTH'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		
		if ( "$colsize" != "Not Needed" ) then
			sed -i 's/TEMPCOLD/'0.00$colsize'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		endif
		
		sed -i 's/TEMPRADTHICK/'"$radthick"'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		
		sed -i 's/TEMPBGTAGONLY/'$BGTAGONLY_OPTION'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		
		if ( "$BGRATE_toUse" != "Not Needed" ) then
			sed -i 's/TEMPBGRATE/'$BGRATE_toUse'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		endif
		
		sed -i 's/TEMPNOSECONDARIES/'$GEANT_NOSECONDARIES'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in

		if ( "$gen_pre" == "file" ) then
			@ skip_num = $FILE_NUMBER * $PER_FILE
	    	sed -i 's/TEMPSKIP/'$skip_num'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
	
		else if ( $GENERATOR == "particle_gun" ) then
			sed -i 's/INFILE/cINFILE/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
			sed -i 's/BEAM/cBEAM/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
			sed -i 's/TEMPSKIP/'0'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
			grep -v "/particle/" $STANDARD_NAME.conf >> control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		else
	    	sed -i 's/TEMPSKIP/'0'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		endif

		if ( "$BKGFOLDSTR" == "None" ) then
	    	echo "removing Beam Photon background from geant simulation"
	    	sed -i 's/BGRATE/cBGRATE/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
	    	sed -i 's/BGGATE/cBGGATE/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
	    	sed -i 's/TEMPMINE/'$GEN_MIN_ENERGY'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		else if ( "$BKGFOLDSTR" == "BeamPhotons" ) then
			sed -i 's/cBEAM/BEAM/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
	    	sed -i 's/TEMPMINE/0.0012/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		else if ( ("$BKGFOLDSTR" == "DEFAULT" || "$BKGFOLDSTR" == "Random" || "$bkgloc_pre" == "loc:") && "$BGTAGONLY_OPTION" == "0") then
	    	sed -i 's/BGRATE/cBGRATE/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
	    	sed -i 's/BGGATE/cBGGATE/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
	    	sed -i 's/TEMPMINE/'$GEN_MIN_ENERGY'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		else 
	    	sed -i 's/TEMPMINE/'$GEN_MIN_ENERGY'/' control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		endif
		
		echo "" >> control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		echo END >> control'_'$formatted_runNumber'_'$formatted_fileNumber.in
		cp $PWD/control'_'$formatted_runNumber'_'$formatted_fileNumber.in $OUTDIR/configurations/geant/

		mv $PWD/control'_'$formatted_runNumber'_'$formatted_fileNumber.in $PWD/control.in
	
		if ( "$GEANTVER" == "3" ) then

			hdgeant -xml=ccdb://GEOMETRY/main_HDDS.xml,run=$RUN_NUMBER
			set geant_return_code=$status

		else if ( "$GEANTVER" == "4" ) then
	    	#make run.mac then call it below
	    	rm -f run.mac
			
			if ( $gen_pre != "file" ) then
				grep "/particle/" $STANDARD_NAME.conf >>! run.mac
			endif
	    	echo "/run/beamOn $EVT_TO_GEN" >>! run.mac
	    	echo "exit" >>! run.mac
			
	    	hdgeant4 -t$NUMTHREADS run.mac
			set geant_return_code=$status
	    	rm run.mac
		else
	    	echo "INVALID GEANT VERSION"
	    	exit 1
		endif

		if ( $geant_return_code != 0 ) then
				echo
				echo
				echo "Something went wrong with hdgeant(4)"
				echo "status code: "$geant_return_code
				exit $geant_return_code
		endif

		if ( ! -f ./$STANDARD_NAME'_geant'$GEANTVER'.hddm' ) then
			echo "An hddm file was not created by Geant.  Terminating MC production.  Please consult logs to diagnose"
			exit 12
		endif
	endif

		set MCSMEAR_Flags=""
		if ( "$SMEAR" == "0" ) then
			set MCSMEAR_Flags="$MCSMEAR_Flags"" -s"
		endif

		if ( "$NOSIPMSATURATION" == "1" ) then
			set MCSMEAR_Flags="$MCSMEAR_Flags"" -T"
		endif

		
		if ( !("$GENR" == "0" && "$GEANT" == "0" && "$SMEAR" == "0" ) ) then
		echo "RUNNING MCSMEAR"
		if ( "$GENR" == "0" && "$GEANT" == "0" ) then
		echo $GENERATOR
		set geant_file=`echo $GENERATOR | cut -c 6-`
		echo $geant_file
		cp $geant_file ./$STANDARD_NAME'_geant'$GEANTVER'.hddm'
		endif
	    if ( "$BKGFOLDSTR" == "BeamPhotons" || "$BKGFOLDSTR" == "None" || "$BKGFOLDSTR" == "TagOnly" ) then
			echo "running MCsmear without folding in random background"
			echo 'mcsmear' $MCSMEAR_Flags' -PTHREAD_TIMEOUT_FIRST_EVENT=3600 -PTHREAD_TIMEOUT=3000 -o'$STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm' $STANDARD_NAME'_geant'$GEANTVER'.hddm'
			mcsmear $MCSMEAR_Flags -PTHREAD_TIMEOUT_FIRST_EVENT=3600 -PTHREAD_TIMEOUT=3000 -o$STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm' $STANDARD_NAME'_geant'$GEANTVER'.hddm'
			set mcsmear_return_code=$status
	    else if ( "$BKGFOLDSTR" == "DEFAULT" || "$BKGFOLDSTR" == "Random" ) then
			rm -f count.py
			if ( $RANDOM_TRIG_NUM_EVT == -1 ) then
	    	echo "import hddm_s" > count.py
	    	echo "print(sum(1 for r in hddm_s.istream('$bkglocstring')))" >>! count.py
	    	set totalnum=`$USER_PYTHON count.py`
	    	rm count.py
			else
				set totalnum=$RANDOM_TRIG_NUM_EVT
			endif

			echo $FILE_NUMBER
			echo $PER_FILE
			echo $totalnum

			set fold_skip_num=`echo "($FILE_NUMBER * $PER_FILE)%$totalnum" | $USER_BC`
			#set bkglocstring="/w/halld-scifs17exp/halld2/home/tbritton/MCwrapper_Development/converted.hddm"
			
			
			if ( $MAKE_MC_USING_XROOTD == 0 ) then
				echo "mcsmear "$MCSMEAR_Flags" -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME"\_"geant$GEANTVER"\_"smeared.hddm $STANDARD_NAME"\_"geant$GEANTVER.hddm $bkglocstring"\:"1""+"$fold_skip_num
				mcsmear $MCSMEAR_Flags -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME\_geant$GEANTVER\_smeared.hddm $STANDARD_NAME\_geant$GEANTVER.hddm $bkglocstring\:1\+$fold_skip_num
			else
				echo "mcsmear $MCSMEAR_Flags -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME\_geant$GEANTVER\_smeared.hddm $STANDARD_NAME\_geant$GEANTVER.hddm $XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm:1+$fold_skip_num"
				mcsmear $MCSMEAR_Flags -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME\_geant$GEANTVER\_smeared.hddm $STANDARD_NAME\_geant$GEANTVER.hddm $XRD_RANDOMS_URL/random_triggers/$RANDBGTAG/run$formatted_runNumber\_random.hddm\:1\+$fold_skip_num
			endif
			set mcsmear_return_code=$status
		else if ( "$bkgloc_pre" == "loc:" ) then
			rm -f count.py
			if ( $RANDOM_TRIG_NUM_EVT == -1 ) then
	    	echo "import hddm_s" > count.py
	    	echo "print(sum(1 for r in hddm_s.istream('$bkglocstring')))" >>! count.py
	    	set totalnum=`$USER_PYTHON count.py`
	    	rm count.py
			else
				set totalnum=$RANDOM_TRIG_NUM_EVT
			endif
			set fold_skip_num=`echo "($FILE_NUMBER * $PER_FILE)%$totalnum" | $USER_BC`
			
			echo "mcsmear "$MCSMEAR_Flags" -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME"\_"geant$GEANTVER"\_"smeared.hddm $STANDARD_NAME"\_"geant$GEANTVER.hddm $bkglocstring"\:"1""+"$fold_skip_num
			mcsmear $MCSMEAR_Flags -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME\_geant$GEANTVER\_smeared.hddm $STANDARD_NAME\_geant$GEANTVER.hddm $bkglocstring\:1\+$fold_skip_num
			set mcsmear_return_code=$status
	    
			else
			#trust the user and use their string
			echo 'mcsmear '$MCSMEAR_Flags' -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o'$STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm'' '$STANDARD_NAME'_geant'$GEANTVER'.hddm'' '$BKGFOLDSTR
			mcsmear $MCSMEAR_Flags -PTHREAD_TIMEOUT_FIRST_EVENT=6400 -PTHREAD_TIMEOUT=6400 -o$STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm' $STANDARD_NAME'_geant'$GEANTVER'.hddm' $BKGFOLDSTR
			set mcsmear_return_code=$status
	    
			endif
		if ( $mcsmear_return_code != 0 ) then
			echo
			echo
			echo "Something went wrong with mcsmear"
			echo "status code: "$mcsmear_return_code
			exit $mcsmear_return_code
		endif

	    #run reconstruction
	    if ( "$CLEANGENR" == "1" ) then
				rm beam.config
				rm $STANDARD_NAME'_beam.conf'
				if ( "$GENERATOR" == "genr8" ) then
		  		rm *.ascii
				else if ( "$GENERATOR" == "bggen" || "$GENERATOR" == "bggen_jpsi" || "$GENERATOR" == "bggen_phi_ee" ) then
		   		rm particle.dat
		   		rm pythia.dat
		   		rm pythia-geant.map
					rm bggen.his
					rm -f bggen.nt
		   		unlink fort.15
				else if ( "$GENERATOR" == "gen_ee_hb" ) then
					rm CFFs_DD_Feb2012.dat 
					rm ee.ascii
					rm cobrems.root
					rm tcs_gen.root
				endif	
				if ( "$GENERATOR" != "particle_gun" && "$gen_pre" != "file" ) then	
					rm $STANDARD_NAME.hddm
				endif
				if ( "$gen_pre" == "file" ) then	
					rm $STANDARD_NAME.hddm
				endif
	    endif
	    
		if ( ! -f ./$STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm' ) then
			echo "An hddm file was not created by mcsmear.  Terminating MC production.  Please consult logs to diagnose"
			exit 13
		endif

	    if ( "$RECON" != "0" ) then
				echo "RUNNING RECONSTRUCTION"
				set file_to_recon=$STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm'

				if ("$GENR" == "0" && "$GEANT" == "0" && "$SMEAR" == "0" ) then
					set file_to_recon="$CONFIG_FILE"
				endif

				set additional_hdroot=""
				if ( "$EXPERIMENT" == "CPP" ) then
					set additional_hdroot="-PKALMAN:ADD_VERTEX_POINT=1"
				endif

				if ( "$RECON_CALIBTIME" != "notime" ) then
					set reconwholecontext = "variation=$VERSION calibtime=$RECON_CALIBTIME"
					setenv JANA_CALIB_CONTEXT "$reconwholecontext"
				endif
				set reaction_filter=""
				#set file_options=""
				if ( "$recon_pre" == "file" ) then
		   		echo "using config file: "$jana_config_file

				echo hd_root $file_to_recon --config=jana_config.cfg -PNTHREADS=$NUMTHREADS -PTHREAD_TIMEOUT=500 $additional_hdroot
		   		hd_root $file_to_recon --config=jana_config.cfg -PNTHREADS=$NUMTHREADS -PTHREAD_TIMEOUT=500 $additional_hdroot
					set hd_root_return_code=$status

					set reaction_filter = `grep ReactionFilter jana_config.cfg`
					#set file_options = `tail jana_config.cfg -n+2` # get everything from line 2 on.  Lines counting starts with 1
					echo "Reaction Filter: "$reaction_filter
					#echo "STATUS: " $hd_root_return_code
					if ( "$reaction_filter" == "" || "$ANAENVIRONMENT" == "no_Analysis_env" ) then
						rm jana_config.cfg
					endif
				else
				
		   		set pluginlist=("danarest" "monitoring_hists" "mcthrown_tree" )

		   		if ( "$CUSTOM_PLUGINS" != "None" ) then
						set pluginlist=( "$pluginlist" "$CUSTOM_PLUGINS" )
		   		endif	
		   		set PluginStr=""
	       
		   		foreach plugin ($pluginlist)
						set PluginStr="$PluginStr""$plugin"","
		   		end
		
		   		set PluginStr=`echo $PluginStr | sed -r 's/.{1}$//'`
		   		echo "Running hd_root with:""$PluginStr"
		   		echo "hd_root ""$STANDARD_NAME"'_geant'"$GEANTVER"'_smeared.hddm'" -PPLUGINS=""$PluginStr ""-PNTHREADS=""$NUMTHREADS"
		   		hd_root $file_to_recon -PPLUGINS=$PluginStr -PNTHREADS=$NUMTHREADS -PTHREAD_TIMEOUT=500 $additional_hdroot
		    	set hd_root_return_code=$status
				
				endif
			
				if ( $hd_root_return_code != 0 ) then
					echo
					echo
					echo "Something went wrong with hd_root"
					echo "Status code: "$hd_root_return_code
					exit $hd_root_return_code
				endif

				if ( -f dana_rest.hddm ) then
					mv dana_rest.hddm dana_rest_$STANDARD_NAME.hddm
				endif

				if ( "$ANAENVIRONMENT" != "no_Analysis_env" && "$reaction_filter" != "" ) then
					echo "new env setup"
					source /group/halld/Software/build_scripts/gluex_env_clean.csh
					set xmltest2=`echo $ANAENVIRONMENT | rev | cut -c -4 | rev`
					if ( "$xmltest2" == ".xml" ) then
						source /group/halld/Software/build_scripts/gluex_env_jlab.csh $ANAENVIRONMENT
					else
						source $ANAENVIRONMENT
					endif
					if ( "$ccdbSQLITEPATH" != "no_sqlite" && "$ccdbSQLITEPATH" != "batch_default" && "$ccdbSQLITEPATH" != "jlab_batch_default" ) then
	if (`$USER_STAT --file-system --format=%T $PWD` == "lustre" ) then
		echo "Attempting to use sqlite on a lustre file system. This does not work.  Try running on a different file system!"
		exit 1
	endif
    cp $ccdbSQLITEPATH ./ccdb.sqlite
    setenv CCDB_CONNECTION sqlite:///$PWD/ccdb.sqlite
    setenv JANA_CALIB_URL ${CCDB_CONNECTION}
else if ( "$ccdbSQLITEPATH" == "batch_default" ) then
    setenv CCDB_CONNECTION sqlite:////group/halld/www/halldweb/html/dist/ccdb.sqlite
    setenv JANA_CALIB_URL ${CCDB_CONNECTION}
else if ( "$ccdbSQLITEPATH" == "jlab_batch_default" ) then
	#	set ccdb_jlab_sqlite_path=`bash -c 'echo $((1 + RANDOM % 100))'`
	#	if ( -f /work/halld/ccdb_sqlite/$ccdb_jlab_sqlite_path/ccdb.sqlite ) then
	#		setenv CCDB_CONNECTION sqlite:////work/halld/ccdb_sqlite/$ccdb_jlab_sqlite_path/ccdb.sqlite
	#	else
	#		setenv CCDB_CONNECTION mysql://ccdb_user@hallddb.jlab.org/ccdb
	#	endif
	setenv CCDB_CONNECTION mysql://ccdb_user@hallddb-farm.jlab.org/ccdb
    setenv JANA_CALIB_URL ${CCDB_CONNECTION}
endif

if ( "$rcdbSQLITEPATH" != "no_sqlite" && "$rcdbSQLITEPATH" != "batch_default" ) then
	if (`$USER_STAT --file-system --format=%T $PWD` == "lustre" ) then
		echo "Attempting to use sqlite on a lustre file system. This does not work.  Try running on a different file system!"
		exit 1
	endif
    cp $rcdbSQLITEPATH ./rcdb.sqlite
    setenv RCDB_CONNECTION sqlite:///$PWD/rcdb.sqlite
else if ( "$rcdbSQLITEPATH" == "batch_default" ) then
	#echo "keeping the RCDB on mysql now"
    setenv RCDB_CONNECTION sqlite:////group/halld/www/halldweb/html/dist/rcdb.sqlite 
endif

					echo "EMULATING ANALYSIS LAUNCH"
					echo "changed software to:  "`which hd_root`
					echo "PLUGINS ReactionFilter" > ana_jana.cfg
					tail jana_config.cfg -n+2 >> ana_jana.cfg

					cat ana_jana.cfg

					hd_root dana_rest_$STANDARD_NAME.hddm --config=ana_jana.cfg -PNTHREADS=$NUMTHREADS -PTHREAD_TIMEOUT=500 -o hd_root_ana_$STANDARD_NAME.root
					set anahd_root_return_code=$status

					if ( $anahd_root_return_code != 0 ) then
					echo
					echo
					echo "Something went wrong with ana_hd_root"
					echo "Status code: "$anahd_root_return_code
					exit $anahd_root_return_code
					endif

					rm jana_config.cfg
					rm ana_jana.cfg

				endif

				if ( "$CLEANGEANT" == "1" && "$GEANT" == "1" ) then
		   		rm $STANDARD_NAME'_geant'$GEANTVER'.hddm'
		   		rm control.in
		   		rm -f geant.hbook
		   		rm -f hdgeant.rz
		   		if ( "$PWD" != "$MCWRAPPER_CENTRAL" ) then
						rm temp_Gcontrol.in	
		   		endif
				endif
		
				if ( "$CLEANSMEAR" == "1" && "$SMEAR" == "1" ) then
		   		rm $STANDARD_NAME'_geant'$GEANTVER'_smeared.hddm'
		   		rm -rf smear.root
				endif
		
				if ( "$CLEANRECON" == "1" ) then
		   		rm dana_rest*
				endif
		
				set rootfiles=`ls *.root`
				set filename_root=""

				foreach rootfile ($rootfiles)
	    		set filename_root=`echo $rootfile | sed -r 's/.{5}$//'`
					set filetomv="$rootfile"
					set filecheck=`echo $current_files | grep -c $filetomv`

					if ( "$filecheck" == "0" ) then
						mv $filetomv $filename_root\_$STANDARD_NAME.root
						echo $filename_root\_$STANDARD_NAME.root
						set hdroot_test=`echo $filename_root\_$STANDARD_NAME.root | grep hd_root_`
						set thrown_test=`echo $filename_root\_$STANDARD_NAME.root | grep tree_thrown`
						set gen_test=`echo $filename_root\_$STANDARD_NAME.root | grep gen_`
						set reaction_test=`echo $filename_root\_$STANDARD_NAME.root | grep tree_`
						#echo hdroot_test = $hdroot_test
						if ($hdroot_test !~ "") then
							echo "hdroot"
							if ( ! -d "$OUTDIR/root/monitoring_hists/" ) then
								#echo "DNE"
								#echo "$OUTDIR/root/monitoring_hists/"
    						mkdir $OUTDIR/root/monitoring_hists/
							endif
							mv $PWD/$filename_root\_$STANDARD_NAME.root $OUTDIR/root/monitoring_hists
						else if ($thrown_test !~ "") then
							echo "thrown"
							if ( ! -d "$OUTDIR/root/thrown/" ) then
								#echo "DNE"
								#echo "$OUTDIR/root/monitoring_hists/"
    						mkdir $OUTDIR/root/thrown/
							endif
							mv $PWD/$filename_root\_$STANDARD_NAME.root $OUTDIR/root/thrown
						else if ($reaction_test !~ "") then
							echo "reaction"
							if ( ! -d "$OUTDIR/root/trees/" ) then
								#echo "DNE"
								#echo "$OUTDIR/root/monitoring_hists/"
    						mkdir $OUTDIR/root/trees/
							endif
							mv $PWD/$filename_root\_$STANDARD_NAME.root $OUTDIR/root/trees
						else if ($gen_test !~ "") then
							echo "gen"
							if ( ! -d "$OUTDIR/root/generator/" ) then
								#echo "DNE"
								#echo "$OUTDIR/root/monitoring_hists/"
    						mkdir $OUTDIR/root/generator/
							endif
							mv $PWD/$filename_root\_$STANDARD_NAME.root $OUTDIR/root/generator
						else
							mv $PWD/$filename_root\_$STANDARD_NAME.root $OUTDIR/root/
						endif
		   			
					endif
				end
	    endif
	

rm -rf .hdds_tmp_*
rm -rf ccdb.sqlite
rm -rf rcdb.sqlite

if ( "$gen_pre" != "file" && "$GENERATOR" != "gen_ee_hb" && "$GENERATOR" != "gen_ee" && "$GENR" == "1" ) then
    mv $PWD/*.conf $OUTDIR/configurations/generation/
endif

set hddmfiles=`ls | grep .hddm`

if ( "$hddmfiles" != "" ) then
	foreach hddmfile ($hddmfiles)
		set filetomv="$hddmfile" 
		set filecheck=`echo $current_files | grep -c $filetomv`
		if ( "$filecheck" == "0" ) then
    		mv $hddmfile $OUTDIR/hddm/
		endif
	end
endif

cd ..

if ( `ls $RUNNING_DIR/${RUN_NUMBER}_${FILE_NUMBER} | wc -l` == 0 ) then
	rm -rf $RUNNING_DIR/${RUN_NUMBER}_${FILE_NUMBER}
else
	echo "MOVING AND/OR CLEANUP FAILED"
	echo `ls $RUNNING_DIR/${RUN_NUMBER}_${FILE_NUMBER}`
endif

#    mv $PWD/*.root $OUTDIR/root/ #just in case
echo `date`
echo "Successfully completed"
