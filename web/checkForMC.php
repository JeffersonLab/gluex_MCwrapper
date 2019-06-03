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


$bkg = $_GET["bkg"];

if ( $_GET["bkg"] == "loc" )
{
    $bkg = $bkg . ":/" . $_GET["randomtag"];
}

if ( $_GET["randomtag"] != "" && $_GET["bkg"] != "loc" )
{
    $bkg = $bkg . ":" . $_GET["randomtag"];
}

$sql = "SELECT * FROM Project where Generator=\"" . $_GET["generator"] . "\" && VersionSet=\"" . $_GET["versionSet"] . "\"";
$sql = $sql . " && BKG=\"" . $bkg ."\"";

//echo $sql;
//echo "<br>";

$result = $conn->query($sql);

$data = array();
if ($result->num_rows > 0) {
// output data of each row
    while($row = $result->fetch_assoc()) {
        $data []= $row;
/*        $tempArray = array();
        $tempArray["ID"] = $row["ID"];
        $tempArray["Job_ID"] = $row["Job_ID"];
        $tempArray["BatchJobID"] = $row["BatchJobID"];
        $containing["data"] []= $tempArray;
        */
     //echo "id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
} 
$conn->close();


echo json_encode($data);
//echo json_encode($containing);
//return json_encode($data);
?>
