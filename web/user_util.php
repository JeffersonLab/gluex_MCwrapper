
<?php

function RecallProject()
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

    $usrcheck="SELECT UName FROM Project where ID=" . $_GET["projID"];
    $checkres=$conn->query($usrcheck);

    $urow = $checkres->fetch_assoc();
    if( $_SERVER['PHP_AUTH_USER'] == $urow["UName"])
    {
        //echo "<br> InTestReset()<br>";
        $sql = "UPDATE Project Set Tested=2 WHERE ID=" . $_GET["projID"];
        //echo $sql . "<br>";

        $result = $conn->query($sql);
        //echo "here";
        //echo $result;
        $conn->commit();

        $conn->close();
        return "FLAGGING PROJECT FOR RECALL IF ABLE";
    }
    $conn->close();
    return "Error.  You do not own this project";

}

function DeclareComplete()
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

    $usrcheck="SELECT UName FROM Project where ID=" . $_GET["projID"];
    $checkres=$conn->query($usrcheck);

    $urow = $checkres->fetch_assoc();
    if( $_SERVER['PHP_AUTH_USER'] == $urow["UName"])
    {
        //echo "<br> InTestReset()<br>";
        $sql = "UPDATE Project Set Tested=4 WHERE ID=" . $_GET["projID"];
        //echo $sql . "<br>";

        $result = $conn->query($sql);
        //echo "here";
        //echo $result;
        $conn->commit();
        $conn->close();
        return "Declaring project complete. Even with uncompleted jobs";
    }
    $conn->close();
    return "Error.  You do not own this project";

}

function CancelProject()
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

    $usrcheck="SELECT UName FROM Project where ID=" . $_GET["projID"];
    $checkres=$conn->query($usrcheck);

    $urow = $checkres->fetch_assoc();
    if( $_SERVER['PHP_AUTH_USER'] == $urow["UName"])
    {


        $compSQL="SELECT COUNT(ID) from Attempts where Status='4' && ExitCode=0 && Job_ID in (SELECT ID FROM Jobs where Project_ID=". $_GET["projID"] .");";

        $result = $conn->query($compSQL);
        $row = $result->fetch_assoc();
  
        if($row["COUNT(ID)"] != 0)
        {
            $conn->close();
            return "Cannot cancel as the project has some completed jobs.  Either 'recall' the project to effectively pause the project.  Or declare it completed";
        }

        //echo "<br> InTestReset()<br>";
        $sql = "UPDATE Project Set Tested=3 WHERE ID=" . $_GET["projID"];
        //echo $sql . "<br>";

        $result = $conn->query($sql);
        //echo "here";
        //echo $result;
        $conn->commit();
        $conn->close();
        return "Declaring project complete. Even with uncompleted jobs";
    }
    $conn->close();
    return "Error.  You do not own this project";

}

   $out="";

    if($_GET["Mode"]=="Recall")
    {
        $out=RecallProject();
    }
    else if($_GET["Mode"]=="DeclareComplete")
    {
        $out=DeclareComplete();
    }
    else if($_GET["Mode"]=="Cancel")
    {
        $out=CancelProject();
    }


echo $out;
return $out;
?>
