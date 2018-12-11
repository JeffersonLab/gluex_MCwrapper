<?php
$servername = "hallddb";
$username = "mcuser";
$password = "";
$dbname = "gluex_mc";
//echo $_GET['qs'] . " ---> " . $_GET['qe'];
// Create connection
$conn = mysqli_connect($servername, $username, $password, $dbname);
// Check connection
if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
}

//GET IPS FROM PROJECTS
$sql="SELECT DISTINCT UIp from Project where UIp is not NULL;";

$result = $conn->query($sql);

if ($result->num_rows > 0) {
// output data of each row
    while($row = $result->fetch_assoc()) {
        $data[]=$row;
        //echo $row["UIp"] . "<br>";//"id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
} 

$sql2="SELECT DISTINCT RunIP from Attempts where RunIP is not NULL && BatchSystem='OSG';";

$result2 = $conn->query($sql2);

if ($result2->num_rows > 0) {
// output data of each row
    while($row2 = $result2->fetch_assoc()) {
        $data2[]=$row2;
        //echo $row["UIp"] . "<br>";//"id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
}


$count=0;
//var_dump($data);
//echo "<br>";
foreach ($data as $row)
{
    $IP_TO_LOOKUP=$row["UIp"];

    $check_DB="SELECT ID FROM Locations WHERE IP=\"" . $IP_TO_LOOKUP . "\"";
    //echo $check_DB . "<br>";
    $check=$conn->query($check_DB);
   // echo "rows ".$check->num_rows . "<br>";

    if($check->num_rows != 0)
    {
        continue;
    }
    //echo $count . "<br>";
    if($count>5)
    {
        break;
    }


   Lookup($conn,$IP_TO_LOOKUP);
    $count=$count+1;
    
    //echo $vars;
    //echo $ret;
   // echo "==================" . "<br>";
}
//var_dump($data2);
//echo "<br>";
foreach ($data2 as $row2)
{
    $IP_TO_LOOKUP2=$row2["RunIP"];

    $check_DB2="SELECT ID FROM Locations WHERE IP=\"" . $IP_TO_LOOKUP2 . "\"";
    //echo $check_DB2 . "<br>";
    $check2=$conn->query($check_DB2);
    //echo "rows ".$check2->num_rows . " <br>";

    if($check2->num_rows != 0)
    {
        continue;
    }
    //echo $count . "<br>";

    Lookup($conn,$IP_TO_LOOKUP2);
    $count=$count+1;
   
    //echo "==================" . "<br>";
}


$fsql="SELECT * FROM Locations;";

$fresult = $conn->query($fsql);

if ($fresult->num_rows > 0) {
// output data of each row
    while($frow = $fresult->fetch_assoc()) {
        $fdata[]=$frow;
        //echo $row["UIp"] . "<br>";//"id: " . $row["id"]. " - Run: " . $row["run"]. "<br>";
    }
} 

$conn->close();

echo json_encode($fdata);
return json_encode($fdata);

function Lookup($conn,$IP)
{
//echo "LOOKUP <br>";
$baseUrlip= "http://api.ipapi.com/";
$key="?access_key=cc138a088a1a86604716a19dc20ad07a";
$ch = curl_init();
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

$urlstr= $baseUrlip .$IP. $key;
    //echo $urlstr . "<br>";
    
    //echo "curl exec <br>";
    
    curl_setopt($ch, CURLOPT_URL, $urlstr);
    

    $ret = curl_exec($ch);
    if ($ret === false) 
    {
    $ret = curl_error($ch);
    //echo $ret . "<br>";
    }
    else
    {
    
    $vars = json_decode($ret , true);
    //var_dump($vars);
    //echo "<br>";

    $IP_TO_USE=$vars["ip"];
    $LONG_TO_USE=NULL;
    $LAT_TO_USE=NULL;
    
    if($vars["longitude"] != NULL)
    {
        //echo "NOT NULL" . "<br>";
        $LONG_TO_USE=$vars["longitude"];
    }
    if($vars["latitude"])
    {
        $LAT_TO_USE=$vars["latitude"];
    }
    $isql = "INSERT INTO Locations (IP, Longitude, Latitude)" . " VALUES (\"".$IP_TO_USE."\"," . $LONG_TO_USE .",". $LAT_TO_USE ."); ";
   // echo $vars["ip"] . " | " . $vars["longitude"] . " | " . $vars["latitude"] . "<br>";
   if($LAT_TO_USE==NULL && $LONG_TO_USE ==NULL)
    {
        //echo "IS NULL" . "<br>";
        $isql = "INSERT INTO Locations (IP,Longitude,Latitude)" . " VALUES (\"".$IP_TO_USE."\",NULL,NULL);";
    }
    
   // echo $isql . "<br>";
    $conn->query($isql);
    $conn->commit();

   
curl_close($ch);
}
}
?>
