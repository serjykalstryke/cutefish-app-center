#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <ui/test_input.h>
#include <ui/keys.h>

template<class T> static T* findView(ui::View* root,std::function<bool(T*)> match){
    if(auto* view=dynamic_cast<T*>(root);view && match(view))return view;
    for(auto& child:root->children())if(auto* found=findView<T>(child.get(),match))return found;
    return nullptr;
}
static ui::Label* text(ui::View* root,const std::string& value){return findView<ui::Label>(root,[&](auto* label){return label->text()==value;});}
static void click(ui::Window& window,ui::View* view){
    assert(view);for(auto* parent=view->parent();parent;parent=parent->parent())if(auto* scroll=dynamic_cast<ui::ScrollView*>(parent)){
        auto point=view->mapToWindow({0,0});auto origin=scroll->contentView()->mapToWindow({0,0});scroll->ensureVisible({point.x-origin.x,point.y-origin.y,view->geometry().width,view->geometry().height});
    }
    window.grab();ui::TestInput::click(window,view->mapToWindow({view->geometry().width/2,view->geometry().height/2}));
}
int main(int argc,char** argv){
    const bool live=argc>1 && std::string(argv[1])=="--live";
    std::filesystem::create_directories("outputs");std::filesystem::create_directories("work/home-fixture");
    if(!live){
        auto backend=(std::filesystem::path(__FILE__).parent_path()/"details_fixture.py").string();setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);
        auto folder=std::filesystem::absolute("work/home-fixture").string();setenv("APP_CENTER_DETAILS_FIXTURE_DIR",folder.c_str(),1);
    }
    ui::Application app(argc,argv,ui::Application::Platform::Headless);AppCenter center(app,false);center.show();auto& window=center.window();window.grab();
    assert(app.mainMenu());assert(app.mainMenu()->submenu(0)->role()==ui::MenuRole::Application);
    base::Timer poll(&app.loop());int stage=0,ticks=0,readyTicks=0;
    poll.onTimeout=[&]{
        if(++ticks>250){std::cerr<<"Timed out at home stage "<<stage<<"\n";app.quit(1);return;}
        window.grab();auto* root=window.contentView();
        if(stage==0 && text(root,"Firefox") && text(root,"LibreOffice") && text(root,"VLC")){
            if(++readyTicks<4)return;
            assert(text(root,"Explore categories"));assert(text(root,"1 / 2"));assert(!text(root,"Your software,\nin one place."));assert(!text(root,"Choose your source"));
            assert(findView<CategoryTile>(root,[](auto*){return true;}));assert(findView<FeaturedCard>(root,[](auto*){return true;}));
            assert(window.grab().savePng(live?"outputs/app-center-discover.png":"work/home-fixture/discover.png"));
            auto* next=findView<ui::Button>(root,[](auto* button){return button->toolTip()=="Next featured apps";});click(window,next);stage=1;
        } else if(stage==1 && text(root,"Krita") && text(root,"2 / 2")){
            click(window,text(root,"About"));stage=2;
        } else if(stage==2 && text(root,"Created by")){
            assert(text(root,"David Stinnett"));assert(text(root,"Cutefish App Center"));assert(text(root,std::string("Version ")+APP_CENTER_VERSION));
            assert(!findView<FeaturedCard>(root,[](auto*){return true;}));
            assert(window.grab().savePng(live?"outputs/app-center-about.png":"work/home-fixture/about.png"));
            click(window,text(root,"Install from File"));stage=3;
        } else if(stage==3 && text(root,"Drop a package here")){
            assert(text(root,"Choose File…"));assert(!text(root,"Created by"));assert(findView<DropPanel>(root,[](auto*){return true;}));
            assert(window.grab().savePng(live?"outputs/app-center-install.png":"work/home-fixture/install.png"));
            if(live){std::cout<<"Live featured catalog, carousel, About credit and local-file page rendered.\n";app.quit();return;}
            auto* drop=findView<ui::FileDropArea>(root,[](auto*){return true;});drop->onDropped({"file:///tmp/Example%20Package.deb"});stage=4;
        } else if(stage==4 && text(root,"Example Package") && text(root,"Install")){
            assert(text(root,"Selected file"));assert(text(root,"Example Package.deb"));assert(!findView<FeaturedCard>(root,[](auto*){return true;}));
            click(window,text(root,"Discover"));stage=5;
        } else if(stage==5 && text(root,"Featured apps") && text(root,"Explore categories")){
            assert(!text(root,"Example Package"));assert(!text(root,"Choose your source"));click(window,text(root,"Internet"));stage=6;
        } else if(stage==6 && text(root,"Example Team") && !text(root,"Loading app details…")){
            auto* search=findView<ui::SearchField>(root,[](auto*){return true;});assert(search->text()=="internet");assert(text(root,"Open"));
            std::cout<<"Discover carousel, category search, About credit, file drop/review and navigation passed.\n";app.quit();
        }
    };
    poll.start(100ms);return app.run();
}
