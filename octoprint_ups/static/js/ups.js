$(function() {
    OctoPrint.socket.onMessage("plugin.ups", function(message) {
        if (message.vars) {
            var status = message.vars["ups.status"];
            var critical = message.vars["battery.critical"];

            console.log("status:", status, "critical:", critical);

            // Estado: Na Rede (azul, 100%)
            if (status === "OL") {
                $("#ups_battery_status").text("Na Rede");
                $("#ups_battery_icon").removeClass().addClass("fa fa-battery-full").css("color", "#007bff");
                $("#ups_battery_fill").css("width", "100%").css("background", "#007bff");
                $("#ups_battery_critical").hide();
            }
            // Estado: Na Bateria (verde, 80%)
            else if (status === "OB" && !critical) {
                $("#ups_battery_status").text("Na Bateria");
                $("#ups_battery_icon").removeClass().addClass("fa fa-battery-three-quarters").css("color", "#28a745");
                $("#ups_battery_fill").css("width", "80%").css("background", "#28a745");
                $("#ups_battery_critical").hide();
            }
            // Estado: Crítico (vermelho, 20%)
            if (critical) {
                $("#ups_battery_status").text("Crítico");
                $("#ups_battery_icon").removeClass().addClass("fa fa-battery-quarter").css("color", "#dc3545");
                $("#ups_battery_fill").css("width", "20%").css("background", "#dc3545");
                $("#ups_battery_critical").show();
            } else {
                $("#ups_battery_status").css("color", "");
                $("#ups_battery_critical").hide();
            }
        }
    });
});