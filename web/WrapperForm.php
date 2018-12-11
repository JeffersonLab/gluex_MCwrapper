<?php
if ( $_GET["useremail"] != "")
{
$dateNOW = date("m-d-Y");
$timeNOW = date("h:i:sa");
$datetimeNOW = date("Ymdhisa");

$rungen = 0;
$savegen = 0;

$rungeant = 0;
$savegeant = 0;

$runsmear = 0;
$savesmear = 0;

$runrecon = 0;
$saverecon = 0;

$geant_secondaries=0;

if ( $_GET["GeantSecondaries"] != "")
{
    $geant_secondaries = 1;
}

if ( $_GET["RunGeneration"] != "")
{
    $rungen = 1;
}
if ( $_GET["SaveGeneration"] != "")
{
    $savegen = 1;
}

if ( $_GET["RunGeant"] != "")
{
    $rungeant = 1;
}
if ( $_GET["SaveGeant"] != "")
{
    $savegeant = 1;
}

if ( $_GET["RunSmear"] != "")
{
    $runsmear = 1;
}
if ( $_GET["SaveSmear"] != "")
{
    $savesmear = 1;
}

if ( $_GET["RunRecon"] != "")
{
    $runrecon = 1;
}
if ( $_GET["SaveRecon"] != "")
{
    $saverecon = 1;
}

$msg = $_GET["username"] . ", I received your request for Monte Carlo on " . $dateNOW . " at " . $timeNOW . "\n";

$addrange="";
$runlow = $_GET["runnumber"];
$runhigh = $runlow;
if ( $_GET["maxRunNum"] != "" )
{
    $addrange=" to " . $_GET["maxRunNum"];
    $runhigh = $_GET["maxRunNum"];
}

$fullOutput = "/lustre/expphy/cache/halld/halld-scratch/REQUESTED_MC/" . $_GET["outputloc"] . "_" . $datetimeNOW . "/";

$msg = $msg . "You have requested " . $_GET["numevents"] . " events to be produced from run number " . $_GET["runnumber"] . $addrange . "\n";
$msg = $msg . "The configuration, will be checked by our team of skilled technicians to ensure you will receive only the finest artisanal Monte Carlo samples.\n";
$msg = $msg . "You will be contacted at " . $_GET["useremail"] . " in the event issues are encountered.\n";
$msg = $msg . "===============================================================================\n";
$msg = $msg . "When completed your output will be found at: " . $fullOutput;
$msg = $msg . "\n\n\n\n";


$configstub = "";
#$configstub = $configstub . "DATA_OUTPUT_BASE_DIR=" . $fullOutput . "\n";

$configstub = $configstub . "NCORES=1\n";

$generator_to_use = $_GET["generator"];

if ( $generator_to_use == "file")
{
    $generator_to_use = "file:/" . $_GET["generator_config"];
}

#$configstub = $configstub . "GENERATOR=" . $generator_to_use . "\n";
#$configstub = $configstub . "GENERATOR_CONFIG=" . $_GET["generator_config"] . "\n";
#$configstub = $configstub . "GEANT_VERSION=" . $_GET["Geantver"] . "\n";

$bkg = $_GET["bkg"];

if ( $_GET["bkg"] == "loc" )
{
    $bkg = $bkg . ":/" . $_GET["randomtag"];
}

if ( $_GET["randomtag"] != "" && $_GET["bkg"] != "loc" )
{
    $bkg = $bkg . ":" . $_GET["randomtag"];
}

#$configstub = $configstub . "BKG=" . $bkg . "\n";

#$msg = $msg . $configstub;
$msg = $msg . "===============================================================================\n";
$msg = $msg . $_GET["addreq"];

$servername = "hallddb.jlab.org";
$username = "mcuser";
$password = "";
$dbname = "gluex_mc";

// Create connection
$conn = new mysqli($servername, $username, $password, $dbname);
// Check connection
if ($conn->connect_error) {
    die("Connection failed: " . $conn->connect_error);
} 




$sql = "INSERT INTO Project (Submitter, Email, Exp, Is_Dispatched, RunNumLow, RunNumHigh, "
       . " NumEvents, GeantVersion, OutputLocation, Submit_Time, RunGeneration, "
       . " SaveGeneration, RunGeant, SaveGeant, RunSmear, SaveSmear, "
       . " RunReconstruction, SaveReconstruction, Generator, Generator_Config, Config_Stub, "
       . " BKG, Comments, GenMinE, GenMaxE,GeantSecondaries,VersionSet,UName,UIp,ReactionLines,RCDBQuery)" 
       . " VALUES (?, ?,'gluex','0', ?, ?, "
       . " ?, ?, ?, now(), ?, "
       . " ?, ?, ?, ?, ?, "
       . " ?, ?, ?, ?, ?, "
       . " ?, ?,?,?,?,?,?,?,?,?) ";
$stmt = $conn->prepare($sql);

$stmt->bind_param("ssiiiisiiiiiiiisssssddisssss", $_GET["username"], $_GET["useremail"], $runlow, $runhigh, $_GET["numevents"], 
                  $_GET["Geantver"], $fullOutput, $rungen, $savegen, $rungeant, 
                  $savegeant, $runsmear, $savesmear, $runrecon, $saverecon, 
                  $_GET["generator"], $_GET["generator_config"], $configstub, $bkg, $_GET["addreq"], $_GET["GenMinE"], $_GET["GenMaxE"],$geant_secondaries,$_GET["versionSet"],$_SERVER['PHP_AUTH_USER'],$_SERVER['REMOTE_ADDR'],$_GET["ReactionLines"],$_GET["rcdbq"]);

  //echo $sql;
//echo "<br>";
if ($stmt->execute() === TRUE) {
   //echo "New record created successfully";
} else {

    echo "Execute failed: (" . $stmt->errno . ") " . $stmt->error;
}
$IDquery = "SELECT MAX(ID) FROM Project";
$idres = $conn->query($IDquery);
$row = $idres->fetch_assoc();
//echo $row["MAX(ID)"];
$conn->close();
//echo $REQ_ID;
//echo $msg;
mail("tbritton@jlab.org," . $_GET["useremail"],"MC Request #" . $row["MAX(ID)"] ,$msg);
echo "<br>";
echo "Thanks for your submission, your request should have been received.  A copy of your request has been emailed to the given address for your records.";
echo "<br>";
echo "Jobs may be monitored via the " . "<a href='https://halldweb.jlab.org/gluex_sim/Dashboard.html'> MCwrapper Dashboard </a>";
}
?>
