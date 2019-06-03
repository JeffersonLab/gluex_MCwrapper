<?php
$servername = "hallddb-ext";
$username = "mcreader";
$password = "";
$dbname = "gluex_mc";
//echo $_GET['qs'] . " ---> " . $_GET['qe'];
// Create connection
$conn = mysqli_connect($servername, $username, $password, $dbname);
// Check connection
if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
}


$sql = "SELECT * FROM Project where ID=" . $_GET["id"];

$result = $conn->query($sql);
$data = array();
if ($result->num_rows > 0) {
// output data of each row
    while($row = $result->fetch_assoc()) {
        $data[]=$row;
     //echo "id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
} 

$vsusername = "vsuser";
$vspassword = "";
$vsdbname = "vsdb";
//echo $_GET['qs'] . " ---> " . $_GET['qe'];
// Create connection
$conn_vs = mysqli_connect($servername, $vsusername, $vspassword, $vsdbname);
// Check connection
if (!$conn_vs) {
    die("Connection failed: " . mysqli_connect_error());
}

$vsreconq="select version from version where packageId in (SELECT id from package where name=\"halld_recon\") && versionSetId in (SELECT id from versionSet where filename=\"" . $data[0]['VersionSet'] . "\");";
//echo $vsreconq;
//echo $conn_vs;
$reconresult = $conn_vs->query($vsreconq);
$recon = $reconresult->fetch_assoc();
//print_r($recon);
$data[0]["recon_ver"]=$recon["version"];

$vssimq="select version from version where packageId in (SELECT id from package where name=\"halld_sim\") && versionSetId in (SELECT id from versionSet where filename=\"" . $data[0]['VersionSet'] . "\");";
$simresult = $conn_vs->query($vssimq);
$sim = $simresult->fetch_assoc();
//print_r($recon);
$data[0]["sim_ver"]=$sim["version"];

$conn->close();
$conn_vs->close();

echo json_encode($data);
return json_encode($data);
?>
