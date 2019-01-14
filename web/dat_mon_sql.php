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

$sql = "SELECT * FROM " . $_GET["Table"];

if ( $_GET["projID"] && $_GET["Table"]=="Jobs")
{
    $sql=$sql . " WHERE Project_ID=" . $_GET["projID"];
}

if($_GET["Table"]=="ProjectF")
{
    //$sql="SELECT * FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID=" . $_GET["projID"] . ") GROUP BY Job_ID;";
    $sql="SELECT ID,Email,Submit_Time,Tested,Is_Dispatched,Dispatched_Time,Completed_Time,RunNumLow,RunNumHigh,NumEvents,Generator,BKG,OutputLocation,RCDBQuery,VersionSet,UIp FROM Project where Notified IS NULL";
//    $sql="SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts,Jobs WHERE Attempts.Job_ID = Jobs.ID && Jobs.Project_ID=" . $_GET["projID"] . " GROUP BY Attempts.Job_ID;";
}

if($_GET["Table"]=="Attempts")
{
    //$sql="SELECT * FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID=" . $_GET["projID"] . ") GROUP BY Job_ID;";
    $sql="SELECT * FROM Attempts WHERE ID IN (SELECT Max(ID) FROM Attempts GROUP BY Job_ID) && Job_ID IN (SELECT ID FROM Jobs WHERE IsActive=1 && Project_ID=" . $_GET["projID"] . ");";
//    $sql="SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts,Jobs WHERE Attempts.Job_ID = Jobs.ID && Jobs.Project_ID=" . $_GET["projID"] . " GROUP BY Attempts.Job_ID;";
}
if($_GET["Table"]=="Ticker")
{
    //$sql="SELECT * FROM Attempts WHERE Job_ID IN (SELECT ID FROM Jobs WHERE Project_ID=" . $_GET["projID"] . ") GROUP BY Job_ID;";
    $sql="SELECT COUNT(ID) FROM Attempts as a WHERE ID IN (SELECT Max(ID) FROM Attempts GROUP BY Job_ID) && Job_ID IN (SELECT ID FROM Jobs where Project_ID in (SELECT ID From Project as P WHERE Notified is NULL)) && ExitCode is NULL;";
//    $sql="SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts,Jobs WHERE Attempts.Job_ID = Jobs.ID && Jobs.Project_ID=" . $_GET["projID"] . " GROUP BY Attempts.Job_ID;";
}
if($_GET["Table"]=="RunMap")
{
    $sql="SELECT RunIP FROM Attempts WHERE RunIP is NOT NULL && BatchSystem=\"OSG\" && Job_ID in (SELECT ID From Jobs where Project_ID=". $_GET["projID"] . ");";
    //$sql="SELECT RunIP FROM Attempts WHERE RunIP is NOT NULL && BatchSystem=\"OSG\";";
//    $sql="SELECT Attempts.*,Max(Attempts.Creation_Time) FROM Attempts,Jobs WHERE Attempts.Job_ID = Jobs.ID && Jobs.Project_ID=" . $_GET["projID"] . " GROUP BY Attempts.Job_ID;";
}

//WITH V1 AS ( SELECT P.ID as PROJ_ID, J.ID as JOB_ID, A.Creation_Time as TIME_STAMP FROM Attempts A JOIN Jobs J ON A.Job_ID = J.ID JOIN PROJECTS P ON P.ID = J.Project_ID ) , V2 AS ( SELECT V1.JOB_ID, MAX(V1.TIME_STAMP) AS CURR_ATTEMPT FROM V1 GROUP BY JOB_ID ) , V3 AS ( SELECT V1.PROJ_ID, V1.JOB_ID, V1.TIME_STAMP FROM V1 JOIN V2 ON V1.TIME_STAMP = V2.CURR_ATTEMPT ) SELECT * FROM V1 WHERE PROJ_ID = 72;
//echo "<br>";
//echo $sql;
//echo "<br>";
$result = $conn->query($sql);
$data = array();
if ($result->num_rows > 0) {
// output data of each row
    while($row = $result->fetch_assoc()) {
        $data[]=$row;
     //echo "id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
} 
$conn->close();

echo json_encode($data);
return json_encode($data);
?>
