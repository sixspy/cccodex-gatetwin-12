import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

export default function 行程账() {
  const [行, 设] = useState([]);
  const [审计, 设审计] = useState([]);
  const 刷 = () => {
    取("/行程账").then(设);
    取("/漂移审计").then(设审计);
  };
  useEffect(() => { 刷(); }, []);
  const 吸收 = (r) => r.出站事件时 < r.进站事件时;
  return (
    <div>
      <h1 className="题">行程账</h1>
      <p className="述">
        进站+出站成对后的正式行程。贯验时与两笔刷卡点互证。闸机时钟回拨造成的
        <strong>小幅负历时</strong>（|负历时|≤站规漂移秒）按口径「漂移秒吸收」成对：历时按 0、写漂移审计；
        超窗负历时拒配旁路，不进本账。
      </p>
      <div className="行"><button className="次" onClick={刷}>刷新</button></div>
      {!行.length ? <div className="空态">暂无行程。先灌成对样例。</div> : (
        <table>
          <thead>
            <tr><th>行程键</th><th>卡号</th><th>进→出</th><th>进站时</th><th>出站时</th><th>历时秒</th><th>漂移</th><th>状态</th></tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.行程键}>
                <td>{r.行程键}</td><td>{r.卡号}</td>
                <td>{r.进站站点键}→{r.出站站点键}</td>
                <td>{r.进站事件时}</td><td>{r.出站事件时}</td>
                <td>{r.历时秒}</td>
                <td>{吸收(r) ? <span className="徽章 警">漂移吸收</span> : "—"}</td>
                <td>{r.状态}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2 className="题" style={{ fontSize: "1.1rem", marginTop: "1.6rem" }}>漂移审计</h2>
      <p className="述">负历时被窗内吸收的成对裁决留痕：原始进出站时、负历时秒、漂移秒、口径。</p>
      {!审计.length ? <div className="空态">暂无漂移审计。</div> : (
        <table>
          <thead>
            <tr><th>#</th><th>行程键</th><th>卡号</th><th>进站时</th><th>出站时</th><th>负历时秒</th><th>漂移秒</th><th>口径</th><th>命运</th></tr>
          </thead>
          <tbody>
            {审计.map((a) => (
              <tr key={a.编号}>
                <td>{a.编号}</td><td>{a.行程键}</td><td>{a.卡号}</td>
                <td>{a.进站事件时}</td><td>{a.出站事件时}</td>
                <td>{a.负历时秒}</td><td>{a.漂移秒}</td><td>{a.口径}</td><td>{a.命运}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
