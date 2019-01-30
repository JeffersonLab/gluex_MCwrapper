<?php
if ($_SERVER['PHP_AUTH_USER'] == "tbritton")
{
    echo "1";
    return "1";
}
echo "0";
return "0";
?>
