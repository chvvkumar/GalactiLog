import {
  Chart,
  LineController,
  BarController,
  ScatterController,
  LineElement,
  BarElement,
  PointElement,
  LinearScale,
  CategoryScale,
  TimeScale,
  Tooltip,
  Filler,
} from "chart.js";

Chart.register(
  LineController,
  BarController,
  ScatterController,
  LineElement,
  BarElement,
  PointElement,
  LinearScale,
  CategoryScale,
  TimeScale,
  Tooltip,
  Filler,
);
