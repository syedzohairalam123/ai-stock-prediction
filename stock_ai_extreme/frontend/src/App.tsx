import {BrowserRouter,Routes,Route,Navigate} from "react-router-dom";
import Layout from "./components/Layout";
import CommandCenter from "./pages/CommandCenter";
import Macro from "./pages/Macro";
import Events from "./pages/Events";
import Company from "./pages/Company";
import Screener from "./pages/Screener";
import Crypto from "./pages/Crypto";
import Analytics from "./pages/Analytics";
export default function App(){
  return <BrowserRouter>
    <Routes>
      <Route element={<Layout/>}>
        <Route path="/" element={<CommandCenter/>}/>
        <Route path="/macro" element={<Macro/>}/>
        <Route path="/events" element={<Events/>}/>
        <Route path="/company" element={<Company/>}/>
        <Route path="/screener" element={<Screener/>}/>
        <Route path="/crypto" element={<Crypto/>}/>
        <Route path="/analytics" element={<Analytics/>}/>
        <Route path="*" element={<Navigate to="/" replace/>}/>
      </Route>
    </Routes>
  </BrowserRouter>;
}
