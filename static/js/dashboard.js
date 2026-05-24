document.addEventListener("DOMContentLoaded", () => {

    /* =========================
       PIE CHART (DONUT)
    ========================= */

    const pieCtx = document.getElementById("pieChart");

    if (pieCtx) {
        new Chart(pieCtx, {
            type: "doughnut",
            data: {
                labels: ["Migrados", "Pendientes"],
                datasets: [{
                    data: [pieData.ok, pieData.error],
                    backgroundColor: [
                         "#16a34a",  // verde
                         "#ef4444"   // rojo
                    ],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "70%",
                plugins: {
                    legend: {
                        position: "top",
                        labels: {
                            usePointStyle: true,
                            pointStyle: "circle",
                            font: {
                                size: 11
                            }
                        }
                    }
                }
            }
        });
    }


    /* =========================
       BAR CHART
    ========================= */

    const barCtx = document.getElementById("barChart");

    if (barCtx) {
        new Chart(barCtx, {
            type: "bar",
            data: {
                labels: barData.labels.map(fecha => {
                const d = new Date(fecha);

                return d.toLocaleDateString('es-ES', {
                    day: '2-digit',
                    month: 'short'
                });
            }),
                datasets: [{
                    label: "Procesos",
                    data: barData.data,
                    backgroundColor: "#3b82f6",
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false   
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                        },
                        grid: {
                            color: "#f1f5f9"
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    }


    /* =========================
       LINE CHART
    ========================= */

    const lineCtx = document.getElementById("lineChart");

    if (lineCtx) {
        new Chart(lineCtx, {
            type: "line",
            data: {
                labels: lineData.labels,
                datasets: [
                    {
                        label: "Errores",
                        data: lineData.error,
                        borderColor: "#ef4444"
                    },
                    {
                        label: "OK",
                        data: lineData.ok,
                        borderColor: "#22c55e"
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
                        labels: {
                            usePointStyle: true,
                            pointStyle: "rect",
                            font: {
                                size: 11
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: "#f1f5f9"
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    }

});