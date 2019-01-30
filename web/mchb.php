<?php
$servername = "hallddb";
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

$mcoverlord_query = "SELECT * FROM MCOverlord ORDER BY ID DESC LIMIT 5;";

$result = $conn->query($mcoverlord_query);
$data = array();
$Overlord_data=array();
if ($result->num_rows > 0) {
// output data of each row
    while($row = $result->fetch_assoc()) {
        $Overlord_data[]=$row;
     //echo "id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
} 

$data["MCOverlord"]=$Overlord_data;

$mcdrone_query = "SELECT * FROM MCDrone ORDER BY ID DESC LIMIT 5;";

$Dresult = $conn->query($mcdrone_query);
$Drone_data=array();
if ($Dresult->num_rows > 0) {
// output data of each row
    while($Drow = $Dresult->fetch_assoc()) {
        $Drone_data[]=$Drow;
     //echo "id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
}
$data["MCDrone"]=$Drone_data;

$mcmover_query = "SELECT * FROM MCMover ORDER BY ID DESC LIMIT 5;";

$Mresult = $conn->query($mcmover_query);
$mover_data=array();
if ($Mresult->num_rows > 0) {
// output data of each row
    while($Mrow = $Mresult->fetch_assoc()) {
        $mover_data[]=$Mrow;
     //echo "id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
}
$data["MCMover"]=$mover_data;

$conn->close();

echo json_encode($data);
return json_encode($data);
?>