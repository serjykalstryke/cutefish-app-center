#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <ui/test_input.h>

template<class T> static T* findView(ui::View* root,std::function<bool(T*)> match){
 if(auto* view=dynamic_cast<T*>(root);view && match(view))return view;
 for(auto& child:root->children())if(auto* found=findView<T>(child.get(),match))return found;
 return nullptr;
}
static ui::Label* text(ui::View* root,const std::string& value){return findView<ui::Label>(root,[&](auto* label){return label->text()==value;});}
static bool contains(ui::View* root,const std::string& value){return findView<ui::Label>(root,[&](auto* label){return label->text().find(value)!=std::string::npos;});}
static void click(ui::Window& window,ui::View* view){
 assert(view);for(auto* parent=view->parent();parent;parent=parent->parent())if(auto* scroll=dynamic_cast<ui::ScrollView*>(parent)){auto p=view->mapToWindow({0,0}),o=scroll->contentView()->mapToWindow({0,0});scroll->ensureVisible({p.x-o.x,p.y-o.y,view->geometry().width,view->geometry().height});}
 window.grab();ui::TestInput::click(window,view->mapToWindow({view->geometry().width/2,view->geometry().height/2}));
}
static ui::ComboBox* combo(ui::View* root,const std::string& first){return findView<ui::ComboBox>(root,[&](auto* c){return !c->items().empty() && c->items()[0]==first;});}
static void choose(ui::ComboBox* c,int n){assert(c);c->setCurrentIndex(n);c->onActivated(n);}
static AppRow* row(ui::View* root,const std::string& name){return findView<AppRow>(root,[&](auto* r){return text(r,name);});}
int main(int argc,char** argv){
 bool live=argc>1 && std::string(argv[1])=="--live";
 auto fixture=std::filesystem::absolute("work/management-fixture");std::filesystem::create_directories(fixture);std::filesystem::create_directories("outputs");
 if(!live){auto provider=(std::filesystem::path(__FILE__).parent_path()/"management_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",provider.c_str(),1);setenv("APP_CENTER_MANAGEMENT_FIXTURE_DIR",fixture.c_str(),1);for(auto f:{"updated","apply.json","fail-source","partial"})std::filesystem::remove(fixture/f);}
 ui::Application app(argc,argv,ui::Application::Platform::Headless);AppCenter center(app,false);center.show();auto& window=center.window();window.grab();click(window,text(window.contentView(),"Installed"));
 base::Timer poll(&app.loop());int stage=0,ticks=0;bool sawAuth=false,sawDownload=false;
 poll.onTimeout=[&]{
  if(++ticks>450){std::cerr<<"Timed out at management stage "<<stage<<"\n";app.quit(1);return;}
  window.grab();auto* root=window.contentView();
  auto* all=findView<ui::DialogButton>(root,[](auto* b){return contains(b,"Update All");});
  if(live){
   if(contains(root," entries") && !contains(root,"Checking for updates") && !contains(root,"Loading app details")){
    assert(!text(root,"Updates"));assert(combo(root,"Applications"));assert(window.grab().savePng("outputs/app-center-installed.png"));
    choose(combo(root,"Applications"),1);window.grab();assert(window.grab().savePng("outputs/app-center-all-software.png"));std::cout<<"Live unified installed list, application filter and update summary rendered.\n";app.quit();
   }return;
  }
  if(stage==0 && all && all->isEnabled() && row(root,"Zulu")){
   assert(!text(root,"Updates"));assert(text(all,"Update All (6)"));assert(!row(root,"libc6"));assert(!row(root,"Core 24"));assert(row(root,"Portable"));
   assert(row(root,"Zulu")->mapToWindow({0,0}).y<row(root,"Alpha")->mapToWindow({0,0}).y);
   assert(contains(root,"3 applications · 3 system components"));
   assert(window.grab().savePng("work/management-fixture/applications.png"));
   choose(combo(root,"Applications"),1);choose(combo(root,"All installed"),1);stage=1;
  }else if(stage==1 && row(root,"libc6")){
   assert(!row(root,"Alpha"));click(window,row(root,"libc6"));stage=2;
  }else if(stage==2 && text(root,"Protected system package") && !text(root,"Loading app details…")){
   auto* update=findView<ui::DialogButton>(root,[](auto* v){return text(v,"Update");});auto* remove=findView<ui::Button>(root,[](auto* v){return text(v,"Remove");});
   assert(update && update->isEnabled());assert(remove && !remove->isEnabled());
   choose(combo(root,"Applications"),0);choose(combo(root,"All sources"),1);stage=3;
  }else if(stage==3 && row(root,"Zulu")){
   assert(text(all,"Update All (6)"));assert(!row(root,"Writer"));click(window,all);stage=4;
  }else if(stage==4){
   for(auto* dialog:app.windows())if(dialog!=&window && text(dialog->contentView(),"Update all software")){
    dialog->grab();assert(contains(dialog->contentView(),"libc6"));assert(contains(dialog->contentView(),"Example Platform"));assert(contains(dialog->contentView(),"Core 24"));
    assert(dialog->grab().savePng("work/management-fixture/review.png"));assert(!std::filesystem::exists(fixture/"apply.json"));click(*dialog,text(dialog->contentView(),"Cancel"));stage=5;break;
   }
  }else if(stage==5 && app.windows().size()==1){click(window,all);stage=6;}
  else if(stage==6){
   for(auto* dialog:app.windows())if(dialog!=&window && text(dialog->contentView(),"Apply Updates")){click(*dialog,text(dialog->contentView(),"Apply Updates"));stage=7;break;}
  }else if(stage==7 && std::filesystem::exists(fixture/"updated")){
   for(auto* dialog:app.windows())if(dialog!=&window && text(dialog->contentView(),"Updates completed")){
    assert(sawAuth && sawDownload);assert(text(dialog->contentView(),"3 of 3 sources completed."));
    assert(text(dialog->contentView(),"A system restart is required."));
    click(*dialog,text(dialog->contentView(),"Close"));stage=8;break;
   }
  }else if(stage==7){
   for(auto* dialog:app.windows())if(dialog!=&window && text(dialog->contentView(),"Applying updates")){
    if(!sawAuth && text(dialog->contentView(),"Waiting for authentication")){
     auto* close=findView<ui::DialogButton>(dialog->contentView(),[](auto* b){return text(b,"Close");});
     assert(close && !close->isEnabled());dialog->onCloseRequested();assert(app.windows().size()==2);sawAuth=true;
    }
    if(!sawDownload && text(dialog->contentView(),"Downloading · 40%")){
     assert(dialog->grab().savePng("work/management-fixture/update-progress.png"));sawDownload=true;
    }
   }
  }else if(stage==8 && contains(root,"No updates available") && contains(root,"Restart required")){
   assert(all && !all->isEnabled());assert(std::filesystem::exists(fixture/"apply.json"));
   std::filesystem::remove(fixture/"updated");std::ofstream(fixture/"partial")<<"cancel auth";click(window,text(root,"Check for Updates"));stage=9;
  }else if(stage==9 && all && all->isEnabled()){click(window,all);stage=10;}
  else if(stage==10){
   for(auto* dialog:app.windows())if(dialog!=&window && text(dialog->contentView(),"Apply Updates")){click(*dialog,text(dialog->contentView(),"Apply Updates"));stage=11;break;}
  }else if(stage==11){
   for(auto* dialog:app.windows())if(dialog!=&window && text(dialog->contentView(),"Updates need attention")){
    auto* content=dialog->contentView();
    assert(text(content,"Completed"));assert(text(content,"Not attempted"));assert(text(content,"Authentication was cancelled."));
    assert(text(content,"A system restart is required."));
    assert(dialog->grab().savePng("work/management-fixture/update-result.png"));
    click(*dialog,text(content,"Close"));stage=12;break;
   }
  }else if(stage==12 && all && all->isEnabled()){
   std::ofstream(fixture/"fail-source")<<"offline";click(window,text(root,"Check for Updates"));stage=13;
  }else if(stage==13 && contains(root,"Some update sources are unavailable")){
   assert(row(root,"Zulu"));assert(all && !all->isEnabled());assert(contains(root,"Source unavailable"));
   std::cout<<"Unified management, authentication and progress, close protection, partial completion and restart passed.\n";app.quit();
  }
 };
 poll.start(100ms);return app.run();
}
