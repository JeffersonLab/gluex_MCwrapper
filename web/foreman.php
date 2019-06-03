<?php

$servername = "hallddb-ext.jlab.org";
$username = "mcreader";
$password = "";
$dbname = "gluex_mc";
$rconn = mysqli_connect($servername, $username, $password, $dbname);
$fsql = "SELECT name from Users where Foreman=1;";
$fresult = $rconn->query($fsql);

$foremen=[];

while ($frow = $fresult->fetch_assoc()) {
    #echo($frow["name"]);
    $foremen[]=$frow["name"];
}
#print_r($fresult->fetch);
$rconn->close();

if (in_array($_SERVER['PHP_AUTH_USER'],$foremen,TRUE))
{
    echo "1";
    return "1";
}
echo "0";
return "0";
?>
