pico-8 cartridge // http://www.pico-8.com
version 41
__lua__
-- oi_pico8_shell.p8
-- sketch-only front-end cart for oi on pico-8-class devices
-- this does not do direct networking; a host bridge is assumed.

app={
 mode="idle",
 online=false,
 title="oi",
 body="press o to open",
 page=1,
 pages={},
 cursor=1,
 last_btn={u=false,d=false,l=false,r=false,o=false,x=false},
 presets={
  "where am i needed?",
  "what changed?",
  "give me a short brief",
  "summarize alerts"
 },
 mailbox_out=nil,
 tick=0
}

function split_pages(text,width,lines)
 local words={}
 for w in all(split(text," ",false)) do
  add(words,w)
 end

 local pages={}
 local page={}
 local line=""

 for w in all(words) do
  local candidate=line=="" and w or (line.." "..w)
  if #candidate<=width then
   line=candidate
  else
   add(page,line)
   line=w
   if #page>=lines then
    add(pages,page)
    page={}
   end
  end
 end

 if line!="" then add(page,line) end
 if #page>0 then add(pages,page) end
 if #pages==0 then add(pages,{""}) end
 return pages
end

function set_card(title,body)
 app.title=title
 app.body=body
 app.pages=split_pages(body,16,6)
 app.page=1
 app.mode="showing"
end

function send_intent(intent,preset)
 -- sketch mailbox write; real build would go through host bridge IPC
 app.mailbox_out={
  type="intent",
  intent=intent,
  preset=preset,
  nonce=app.tick
 }
 app.mode="waiting"
 app.title="oi"
 app.body="asking oi..."
 app.pages=split_pages(app.body,16,6)
 app.page=1
end

function mock_bridge_poll()
 -- placeholder for local IPC read
 -- to keep the sketch demonstrable, fake a response after a short delay
 if app.mode=="waiting" and app.tick%90==0 then
  app.online=true
  set_card("oi","all quiet. one thing to check: kitchen sensor battery low.")
 end
end

function pressed(name,current)
 local was=app.last_btn[name]
 app.last_btn[name]=current
 return current and not was
end

function handle_idle()
 if pressed("o",btn(4)) then
  app.mode="menu"
 end
end

function handle_menu()
 if pressed("u",btn(2)) then
  app.cursor=max(1,app.cursor-1)
 end
 if pressed("d",btn(3)) then
  app.cursor=min(#app.presets,app.cursor+1)
 end
 if pressed("o",btn(4)) then
  send_intent("send_preset",app.presets[app.cursor])
 end
 if pressed("x",btn(5)) then
  app.mode="idle"
 end
end

function handle_showing()
 if pressed("u",btn(2)) then
  app.page=max(1,app.page-1)
 end
 if pressed("d",btn(3)) then
  app.page=min(#app.pages,app.page+1)
 end
 if pressed("x",btn(5)) then
  app.mode="idle"
 end
end

function handle_waiting()
 if pressed("x",btn(5)) then
  app.mode="idle"
  app.body="cancelled"
  app.pages=split_pages(app.body,16,6)
  app.page=1
 end
end

function _update60()
 app.tick+=1
 mock_bridge_poll()

 if app.mode=="idle" then
  handle_idle()
 elseif app.mode=="menu" then
  handle_menu()
 elseif app.mode=="waiting" then
  handle_waiting()
 elseif app.mode=="showing" then
  handle_showing()
 end
end

function draw_frame()
 cls(1)
 rect(2,2,125,125,6)
 rectfill(4,4,123,18,2)
 print(app.title,8,9,7)
 print(app.online and "online" or "offline",86,9,11)
end

function draw_idle()
 print("o: open",12,34,7)
 print("tiny oi shell",12,46,6)
 print("bridge required",12,58,5)
end

function draw_menu()
 print("presets",10,24,10)
 for i=1,#app.presets do
  local y=34+(i-1)*16
  local c=i==app.cursor and 11 or 7
  if i==app.cursor then rectfill(8,y-2,119,y+8,13) end
  print(app.presets[i],12,y,c)
 end
end

function draw_showing()
 local lines=app.pages[app.page]
 for i=1,#lines do
  print(lines[i],10,26+(i-1)*12,7)
 end
  print(app.page.."/"..#app.pages,98,112,6)
  print("x: back",10,112,5)
end

function draw_waiting()
 print("thinking...",12,34,10)
 print("x: cancel",12,50,5)
end

function _draw()
 draw_frame()
 if app.mode=="idle" then
  draw_idle()
 elseif app.mode=="menu" then
  draw_menu()
 elseif app.mode=="waiting" then
  draw_waiting()
 elseif app.mode=="showing" then
  draw_showing()
 end
end
