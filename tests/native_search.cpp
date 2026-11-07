#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <ui/test_input.h>

template<class T> static T* find(ui::View* root,std::function<bool(T*)> match){
 if(auto* v=dynamic_cast<T*>(root);v && match(v))return v;
 for(auto& child:root->children())if(auto* v=find<T>(child.get(),match))return v;
 return nullptr;
}
static ui::Label* text(ui::View* root,const std::string& value){return find<ui::Label>(root,[&](auto* l){return l->text()==value;});}
static void click(ui::Window& w,ui::View* v){assert(v);w.grab();ui::TestInput::click(w,v->mapToWindow({v->geometry().width/2,v->geometry().height/2}));}
static ui::ComboBox* choices(ui::View* root){return find<ui::ComboBox>(root,[](auto* c){return c->items().size()==5 && c->items()[0].starts_with("Snap");});}
static void choose(ui::View* root,int n){auto* c=choices(root);assert(c);c->setCurrentIndex(n);c->onActivated(n);}
int main(int argc,char** argv){
 const bool live=argc>1 && std::string(argv[1])=="--live";
 const auto fixture=std::filesystem::absolute("work/search-fixture");std::filesystem::create_directories(fixture);std::filesystem::create_directories("outputs");
 if(!live){auto backend=(std::filesystem::path(__FILE__).parent_path()/"search_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);setenv("APP_CENTER_SEARCH_FIXTURE_DIR",fixture.c_str(),1);for(auto file:{"launch.json","plan.json"})std::filesystem::remove(fixture/file);}
 ui::Application app(argc,argv,ui::Application::Platform::Headless);AppCenter center(app,false);center.show();auto& w=center.window();w.grab();
 auto* search=find<ui::SearchField>(w.contentView(),[](auto*){return true;});assert(search);search->setText(live?"firefox":"example");search->onAccepted();
 base::Timer poll(&app.loop());int stage=0,ticks=0;
 poll.onTimeout=[&]{
  if(++ticks>400){std::cerr<<"Search test timeout at stage "<<stage<<"\n";app.quit(1);return;}
  w.grab();auto* root=w.contentView();
  if(live){
   auto* source=find<ui::ComboBox>(root,[](auto* c){return c->items().size()>=3 && c->items()[0].starts_with("Flatpak");});
   if(source && text(root,"Firefox") && !text(root,"Loading app details…")){
    if(ticks<80 && text(root,"Screenshots") && !find<ui::ImageView>(root,[](auto* view){return view->status()==ui::ImageView::Status::Ready;}))return;
    assert(w.grab().savePng("outputs/app-center-unified-search.png"));std::cout<<"Live Firefox application card and provider choices rendered.\n";app.quit();
   }return;
  }
  if(stage==0 && choices(root) && text(root,"snap Publisher") && !text(root,"Loading app details…")){
   assert(text(root,"2 results · best matches first"));assert(text(root,"Example Browser"));assert(text(root,"Debian · Flatpak · Snap · AppImage"));assert(text(root,"Installed"));assert(text(root,"Open"));assert(text(root,"Remove"));
   assert(choices(root)->items()[0].find("Installed")!=std::string::npos);
   assert(w.grab().savePng("work/search-fixture/unified.png"));click(w,text(root,"Open"));stage=1;
  }else if(stage==1 && std::filesystem::exists(fixture/"launch.json")){choose(root,1);stage=2;}
  else if(stage==2 && text(root,"deb Publisher") && text(root,"Install") && !text(root,"Loading app details…")){
   assert(text(root,"Example Browser"));assert(text(root,"Installed from another source"));assert(!text(root,"Open"));click(w,text(root,"Install"));stage=3;
  }else if(stage==3 && std::filesystem::exists(fixture/"plan.json")){
   for(auto* dialog:app.windows())if(dialog!=&w && text(dialog->contentView(),"Cancel")){click(*dialog,text(dialog->contentView(),"Cancel"));stage=4;break;}
  }else if(stage==4 && app.windows().size()==1){choose(root,2);stage=5;}
  else if(stage==5 && text(root,"Loading app details…")){choose(root,4);stage=6;}
  else if(stage==6 && text(root,"appimage Publisher") && text(root,"Open download page…")){
   assert(text(root,"Example Browser"));assert(!text(root,"Install"));
   auto* other=find<AppRow>(root,[](auto* row){return text(row,"Other App");});click(w,other);stage=7;
  }else if(stage==7 && text(root,"flatpak Publisher") && !choices(root)){
   auto* first=find<AppRow>(root,[](auto* row){return text(row,"Example Browser");});click(w,first);stage=8;
  }else if(stage==8 && text(root,"appimage Publisher") && choices(root) && choices(root)->currentIndex()==4){
   choose(root,3);stage=9;
  }else if(stage==9 && text(root,"flatpak Publisher") && !text(root,"Loading app details…")){
   assert(choices(root)->currentIndex()==3);assert(choices(root)->items()[3].find("user")!=std::string::npos);assert(text(root,"Example Browser"));assert(text(root,"Install"));
   assert(w.grab().savePng("work/search-fixture/selected-source.png"));
   std::cout<<"One application card, five exact source choices, installed preference, source-bound actions, stale-details cancellation and remembered choice passed.\n";app.quit();
  }
 };
 poll.start(80ms);return app.run();
}
