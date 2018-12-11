
<?php

function NotifyComplete()
{
    $servername = "hallddb.jlab.org";
    $username = "mcreader";
    if ($_SERVER['PHP_AUTH_USER'] == "tbritton")
    {
        $username = "mcuser";
    }
    $password = "";
    $dbname = "gluex_mc";
    $conn = mysqli_connect($servername, $username, $password, $dbname);
// Check connection
    if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
    }

    //echo "<br> In NotifyComplete()";
    $sql = " SELECT ID, Submitter, Email, OutputLocation, FinalDestination FROM Project WHERE ID=?";
    
    $stmt = $conn->prepare($sql);
    
    $stmt->bind_param("i", $_GET['projID'] );
    
    $msg="";
    if ($stmt->execute() == TRUE) {
        $stmt->store_result();
        $id="0";
        $submitter="na";
        $email="blah";
        $outputloc="./";
        $finaldest="";
        $stmt->bind_result($id,$submitter, $email, $outputloc, $finaldest);
        $stmt->fetch();
            // output data of each row
    
    
     $msg="Dear ";
     $msg= $msg . $submitter . ",\n";
     $msg = $msg . "\n\n";
     $msg = $msg . "Your MC sample (#" . $id . ") has been completed and may be found: \n";
     if (is_null($finaldest))
     {
        $msg = $msg . $outputloc;
     }
     else
     {
        $msg = $msg . $finaldest;
     }
     echo $msg;
     if($id != 0 && $submitter != "blah")
     {
     mail($email,"GlueX MC Request #" . $id . " Completed" ,$msg);
     }


    $sql2 = "UPDATE Project Set Notified=1 WHERE ID=?";
    $stmt2 = $conn->prepare($sql2);
    
    $stmt2->bind_param("i", $_GET['projID'] );
    $stmt2->execute();

    }
    else
    {
        echo "<br>Query Failed";
    }
     $stmt->free_result();
    
     /* close statement */
     $stmt->close();
     $conn->close();
     return "Notified of Completion";
}

function FullProjectReset()
{
    $servername = "hallddb.jlab.org";
    $username = "mcuser";
    $password = "";
    $dbname = "gluex_mc";
    $conn = mysqli_connect($servername, $username, $password, $dbname);
// Check connection
    if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
    }

    //echo "<br> In FullReset()<br>";
    $sql = "DELETE FROM Attempts where Job_ID in ( SELECT ID FROM Jobs WHERE Project_ID=" . $_GET["projID"]." );";
    //echo $sql;
    $sql2 = "DELETE FROM Jobs WHERE Project_ID=" . $_GET["projID"].";";
    $sql3 = "UPDATE Project SET Is_Dispatched='0',Completed_Time=NULL,Dispatched_Time=NULL WHERE ID=" . $_GET["projID"].";";

    $result = $conn->query($sql);

$result2 = $conn->query($sql2);

$result3 = $conn->query($sql3);


     $conn->close();
     return "RESET COMPLETE";
}
function RetestProject()
{
    $servername = "hallddb.jlab.org";
    $username = "mcuser";
    $password = "";
    $dbname = "gluex_mc";
    $conn = mysqli_connect($servername, $username, $password, $dbname);
// Check connection
    if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
    }

    //echo "<br> InTestReset()<br>";
    $sql = "UPDATE Project Set Tested=0 WHERE ID=" . $_GET["projID"];
    //echo $sql . "<br>";

    $result = $conn->query($sql);
    //echo "here";
    //echo $result;
    $conn->commit();

     $conn->close();
     return "READY TO RESTEST PROJECT";
}

if ($_SERVER['PHP_AUTH_USER'] == "tbritton")
{   $out="";
    if($_GET["Mode"] == 'NotifyComplete')
    {
       $out=NotifyComplete();
    }
    else if($_GET["Mode"]=="FullReset")
    {
        FullProjectReset();
    }
    else if($_GET["Mode"]=="ReTest")
    {
        RetestProject();
    }

}
echo $out;
return $out;
?>
